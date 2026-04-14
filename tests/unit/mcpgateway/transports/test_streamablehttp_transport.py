# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/transports/test_streamablehttp_transport.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for **mcpgateway.transports.streamablehttp_transport**
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
import json
from types import SimpleNamespace
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException
import httpx
from mcp.types import PromptArgument
import pytest
from starlette.types import Scope

# First-Party
# ---------------------------------------------------------------------------
# Import module under test - we only need the specific classes / functions
# ---------------------------------------------------------------------------
from mcpgateway.services.oauth_manager import OAuthEnforcementUnavailableError, OAuthRequiredError
from mcpgateway.transports import streamablehttp_transport as tr  # noqa: E402
from mcpgateway.transports.streamablehttp_transport import (
    _MCPGATEWAY_CONTEXT_KEY,
    list_prompts,
    list_resources,
    list_tools,
    prompt_service,
    resource_service,
    server_id_var,
    tool_service,
    user_context_var,
)

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
async def test_event_store_store_event_eviction_none_entry():
    """Eviction branch should tolerate an unexpected None entry in a full buffer."""
    store = InMemoryEventStore(max_events_per_stream=2)
    stream_id = "s"

    # Create a "full" buffer with a None entry at the next eviction index. This can happen if
    # the buffer is manipulated externally or partially initialized.
    store.streams[stream_id] = tr.StreamBuffer(entries=[None, None], start_seq=0, next_seq=2, count=2)

    event_id = await store.store_event(stream_id, {"id": 99})
    assert event_id in store.event_index
    assert store.streams[stream_id].start_seq == 1


@pytest.mark.asyncio
async def test_event_store_replay_events_after_not_found(caplog):
    """replay_events_after returns None and logs if event not found."""
    store = InMemoryEventStore()
    sent = []
    result = await store.replay_events_after("notfound", sent.append)
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


@pytest.mark.asyncio
async def test_rust_event_store_store_and_replay(monkeypatch):
    """RustEventStore should proxy store/replay operations through the sidecar."""
    captured_requests = []

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeClient:
        async def post(self, url, json=None, timeout=None, follow_redirects=None):  # noqa: A002
            captured_requests.append((url, json, timeout.read, follow_redirects))
            if url.endswith("/store"):
                return FakeResponse({"eventId": "event-123"})
            return FakeResponse(
                {
                    "streamId": "stream-1",
                    "events": [
                        {"eventId": "event-124", "message": {"id": 2}},
                        {"eventId": "event-125", "message": {"id": 3}},
                    ],
                }
            )

    monkeypatch.setattr(tr, "_get_rust_event_store_client", AsyncMock(return_value=FakeClient()))
    monkeypatch.setattr(tr.settings, "experimental_rust_mcp_runtime_timeout_seconds", 17)
    monkeypatch.setattr(tr.settings, "experimental_rust_mcp_runtime_url", "http://127.0.0.1:8787")

    store = tr.RustEventStore(max_events_per_stream=77, ttl=321, key_prefix="mcpgw:eventstore:test")
    event_id = await store.store_event("stream-1", {"id": 1})

    replayed = []

    async def collector(msg):
        replayed.append(msg)

    stream_id = await store.replay_events_after(event_id, collector)

    assert event_id == "event-123"
    assert stream_id == "stream-1"
    assert replayed == [{"id": 2}, {"id": 3}]
    assert captured_requests[0][0] == "http://127.0.0.1:8787/_internal/event-store/store"
    assert captured_requests[0][1] == {
        "streamId": "stream-1",
        "message": {"id": 1},
        "keyPrefix": "mcpgw:eventstore:test",
        "maxEventsPerStream": 77,
        "ttlSeconds": 321,
    }
    assert captured_requests[0][2] == 17
    assert captured_requests[0][3] is False
    assert captured_requests[1][0] == "http://127.0.0.1:8787/_internal/event-store/replay"
    assert captured_requests[1][1] == {
        "lastEventId": "event-123",
        "keyPrefix": "mcpgw:eventstore:test",
    }
    assert captured_requests[1][3] is False


@pytest.mark.asyncio
async def test_rust_event_store_replay_rejects_redirects_without_following(monkeypatch):
    """Replay requests should fail closed on redirects from the Rust sidecar."""
    requests_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(str(request.url))
        if request.url.path.endswith("/replay"):
            return httpx.Response(
                307,
                headers={"location": "http://127.0.0.1:8787/final"},
                request=request,
            )
        return httpx.Response(200, json={"streamId": "unexpected", "events": []}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(tr, "_get_rust_event_store_client", AsyncMock(return_value=client))
    monkeypatch.setattr(tr.settings, "experimental_rust_mcp_runtime_url", "http://127.0.0.1:8787")

    store = tr.RustEventStore()

    try:
        with pytest.raises(httpx.HTTPStatusError, match="307 Temporary Redirect"):
            await store.replay_events_after("event-123", AsyncMock())
    finally:
        await client.aclose()

    assert requests_seen == ["http://127.0.0.1:8787/_internal/event-store/replay"]


@pytest.mark.asyncio
async def test_rust_event_store_store_rejects_invalid_event_id(monkeypatch):
    """RustEventStore should reject empty or invalid event ids from the sidecar."""

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"eventId": ""}

    class FakeClient:
        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(tr, "_get_rust_event_store_client", AsyncMock(return_value=FakeClient()))

    store = tr.RustEventStore()
    with pytest.raises(RuntimeError, match="invalid eventId"):
        await store.store_event("stream-1", {"id": 1})


@pytest.mark.asyncio
async def test_rust_event_store_replay_skips_invalid_entries(monkeypatch):
    """Replay should skip malformed entries and return None for invalid stream ids."""

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self):
            self.calls = 0

        async def post(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return FakeResponse({"streamId": "", "events": []})
            return FakeResponse({"streamId": "stream-1", "events": ["bad", {"message": {"id": 2}}]})

    client = FakeClient()
    monkeypatch.setattr(tr, "_get_rust_event_store_client", AsyncMock(return_value=client))

    store = tr.RustEventStore()
    assert await store.replay_events_after("event-1", AsyncMock()) is None

    replayed = []

    async def collector(msg):
        replayed.append(msg)

    assert await store.replay_events_after("event-2", collector) == "stream-1"
    assert replayed == [{"id": 2}]


@pytest.mark.asyncio
async def test_get_rust_event_store_client_uses_shared_http_client_without_uds(monkeypatch):
    """Without UDS configured, the Rust event-store client should use the shared HTTP client."""
    shared_client = AsyncMock()
    monkeypatch.setattr(tr, "_rust_event_store_client", None)
    monkeypatch.setattr(tr.settings, "experimental_rust_mcp_runtime_uds", None)
    monkeypatch.setattr(tr, "get_http_client", AsyncMock(return_value=shared_client))

    assert await tr._get_rust_event_store_client() is shared_client


@pytest.mark.asyncio
async def test_get_rust_event_store_client_reuses_uds_client(monkeypatch):
    """UDS-backed Rust event-store client should be created once and then reused."""
    constructed = {"count": 0, "kwargs": None}

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            constructed["count"] += 1
            constructed["kwargs"] = _kwargs

    monkeypatch.setattr(tr, "_rust_event_store_client", None)
    monkeypatch.setattr(tr.settings, "experimental_rust_mcp_runtime_uds", "/tmp/contextforge-mcp-rust.sock")
    monkeypatch.setattr(tr, "httpx", MagicMock(AsyncClient=FakeAsyncClient, AsyncHTTPTransport=httpx.AsyncHTTPTransport, Timeout=httpx.Timeout))

    first = await tr._get_rust_event_store_client()
    second = await tr._get_rust_event_store_client()

    assert first is second
    assert constructed["count"] == 1
    assert constructed["kwargs"]["follow_redirects"] is False


def test_safe_str_attr_returns_str():
    """_safe_str_attr returns the attribute when it is a string."""
    obj = SimpleNamespace(title="hello")
    assert tr._safe_str_attr(obj, "title") == "hello"


def test_safe_str_attr_returns_none_for_missing():
    """_safe_str_attr returns None when the attribute is absent."""
    obj = SimpleNamespace()
    assert tr._safe_str_attr(obj, "title") is None


def test_safe_str_attr_returns_none_for_non_str():
    """_safe_str_attr returns None when the attribute is not a string (e.g. MagicMock)."""
    obj = MagicMock()
    assert tr._safe_str_attr(obj, "title") is None


def test_get_streamable_http_auth_context_returns_empty_for_non_dict_context():
    """Non-dict auth contexts should not be forwarded to trusted internal hops."""
    token = tr.user_context_var.set("not-a-dict")
    try:
        assert tr.get_streamable_http_auth_context() == {}
    finally:
        tr.user_context_var.reset(token)


def test_get_streamable_http_auth_context_copies_supported_keys_and_lists():
    """Forwarded auth context should copy supported keys and clone list values."""
    original = {
        "email": "user@example.com",
        "teams": ["team-a"],
        "auth_method": "jwt",
        "is_authenticated": True,
        "is_admin": False,
        "token_use": "session",
        "permission_is_admin": True,
        "scoped_permissions": ["tools.read"],
        "scoped_server_id": "srv-1",
        "ignored": "value",
    }
    token = tr.user_context_var.set(original)
    try:
        forwarded = tr.get_streamable_http_auth_context()
    finally:
        tr.user_context_var.reset(token)

    assert forwarded == {
        "email": "user@example.com",
        "teams": ["team-a"],
        "auth_method": "jwt",
        "is_authenticated": True,
        "is_admin": False,
        "token_use": "session",
        "permission_is_admin": True,
        "scoped_permissions": ["tools.read"],
        "scoped_server_id": "srv-1",
    }
    assert forwarded["teams"] is not original["teams"]
    assert forwarded["scoped_permissions"] is not original["scoped_permissions"]


def test_record_mcp_auth_cache_event_swallows_metrics_errors(monkeypatch):
    """Metrics failures must not break MCP auth cache instrumentation."""

    class BrokenCounter:
        def labels(self, **_kwargs):
            raise RuntimeError("metrics down")

    monkeypatch.setattr(tr, "mcp_auth_cache_events_counter", BrokenCounter())

    tr._record_mcp_auth_cache_event("cache_miss")


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
    # Explicitly set optional metadata to None to avoid MagicMock Pydantic validation issues
    mock_content.annotations = None
    mock_content.meta = None
    mock_result.content = [mock_content]

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    # Ensure no accidental 'structured_content' MagicMock attribute is present
    mock_result.structured_content = None
    # Prevent model_dump from returning a MagicMock with a 'structuredContent' key
    mock_result.model_dump = lambda by_alias=True: {}

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    result = await call_tool("mytool", {"foo": "bar"})
    assert isinstance(result, list)
    assert isinstance(result[0], types.TextContent)
    assert result[0].type == "text"
    assert result[0].text == "hello"


@pytest.mark.asyncio
async def test_call_tool_with_structured_content(monkeypatch):
    """Test call_tool returns tuple with both unstructured and structured content."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, types

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_content = MagicMock()
    mock_content.type = "text"
    mock_content.text = '{"result": "success"}'
    # Explicitly set optional metadata to None to avoid MagicMock Pydantic validation issues
    mock_content.annotations = None
    mock_content.meta = None
    mock_result.content = [mock_content]

    # Simulate structured content being present
    mock_structured = {"status": "ok", "data": {"value": 42}}
    mock_result.structured_content = mock_structured
    mock_result.model_dump = lambda by_alias=True: {"content": [{"type": "text", "text": '{"result": "success"}'}], "structuredContent": mock_structured}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    result = await call_tool("mytool", {"foo": "bar"})

    # When structured content is present, result should be a tuple
    assert isinstance(result, tuple)
    assert len(result) == 2

    # First element should be the unstructured content list
    unstructured, structured = result
    assert isinstance(unstructured, list)
    assert len(unstructured) == 1
    assert isinstance(unstructured[0], types.TextContent)
    assert unstructured[0].text == '{"result": "success"}'

    # Second element should be the structured content dict
    assert isinstance(structured, dict)
    assert structured == mock_structured
    assert structured["status"] == "ok"
    assert structured["data"]["value"] == 42


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

    with caplog.at_level("WARNING", logger="mcpgateway.transports.streamablehttp_transport"):
        result = await call_tool("mytool", {"foo": "bar"})
        assert result == []
        assert "No content returned by tool: mytool" in caplog.text


@pytest.mark.asyncio
async def test_call_tool_exception(monkeypatch, caplog):
    """Test call_tool re-raises exception after logging for proper MCP SDK error handling."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(side_effect=Exception("fail!")))

    with caplog.at_level("ERROR"):
        with pytest.raises(Exception, match="fail!"):
            await call_tool("mytool", {"foo": "bar"})
        assert "Error calling tool 'mytool': fail!" in caplog.text


@pytest.mark.asyncio
async def test_call_tool_requires_tools_execute_permission(monkeypatch):
    """Authenticated Streamable HTTP calls must enforce tools.execute."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service

    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default",
        AsyncMock(
            return_value=(
                "server-1",
                {},
                {"email": "dev@example.com", "teams": ["team-1"], "is_admin": False, "is_authenticated": True},
            )
        ),
    )
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._check_streamable_permission", AsyncMock(return_value=False))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", False)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda _headers: None)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock())

    with pytest.raises(PermissionError, match="Access denied"):
        await call_tool("mytool", {"foo": "bar"})

    tool_service.invoke_tool.assert_not_called()


@pytest.mark.asyncio
async def test_validate_streamable_session_access_denies_non_owner(monkeypatch):
    """Session access helper denies non-admin callers for another owner's session."""
    session_registry = MagicMock()
    session_registry.get_session_owner = AsyncMock(return_value="owner@example.com")
    session_registry.session_exists = AsyncMock(return_value=True)

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._get_shared_session_registry", lambda: session_registry)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    allowed, status, detail = await tr._validate_streamable_session_access(
        mcp_session_id="sess-abc",
        user_context={"email": "attacker@example.com", "is_admin": False, "is_authenticated": True},
        rpc_method="ping",
    )

    assert allowed is False
    assert status == 403
    assert "Session access denied" in detail


@pytest.mark.asyncio
async def test_validate_streamable_session_access_fake_session_not_found(monkeypatch):
    """Session access helper returns 404 when no owner exists and session is unknown."""
    session_registry = MagicMock()
    session_registry.get_session_owner = AsyncMock(return_value=None)
    session_registry.session_exists = AsyncMock(return_value=False)

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._get_shared_session_registry", lambda: session_registry)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    allowed, status, detail = await tr._validate_streamable_session_access(
        mcp_session_id="sess-fake",
        user_context={"email": "dev@example.com", "is_admin": False, "is_authenticated": True},
        rpc_method="ping",
    )

    assert allowed is False
    assert status == 404
    assert "Session not found" in detail


@pytest.mark.asyncio
async def test_validate_streamable_session_access_skips_when_rust_already_validated(monkeypatch):
    """Trusted Rust-validated session requests should skip duplicate Python owner checks."""
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    session_registry = MagicMock()
    session_registry.get_session_owner = AsyncMock(side_effect=AssertionError("should not be called"))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._get_shared_session_registry", lambda: session_registry)

    allowed, status, detail = await tr._validate_streamable_session_access(
        mcp_session_id="sess-rust",
        user_context={"email": "user@example.com", "is_admin": False, "is_authenticated": True, "_rust_session_validated": True},
        rpc_method="tools/call",
    )

    assert allowed is True
    assert status == 200
    assert detail == ""


@pytest.mark.asyncio
async def test_list_tools_with_server_id(monkeypatch):
    """Test list_tools returns tools for a server_id."""
    mock_db = MagicMock()
    mock_tool = MagicMock()
    mock_tool.name = "t"
    mock_tool.title = "Tool Title"
    mock_tool.description = "desc"
    mock_tool.input_schema = {"type": "object"}
    mock_tool.output_schema = None
    mock_tool.annotations = {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "list_server_tools", AsyncMock(return_value=[mock_tool]))

    # Set authenticated user context to bypass OAuth enforcement
    user_token = user_context_var.set({"is_authenticated": True, "sub": "test@example.com"})
    server_token = server_id_var.set("123")
    result = await list_tools()

    assert isinstance(result, list)
    assert result[0].name == "t"
    assert getattr(result[0], "title", None) == "Tool Title"
    assert result[0].description == "desc"

    server_id_var.reset(server_token)
    user_context_var.reset(user_token)


@pytest.mark.asyncio
async def test_list_tools_no_server_id(monkeypatch):
    """Test list_tools returns tools when no server_id is set."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_tools, server_id_var, tool_service

    mock_db = MagicMock()
    mock_tool = MagicMock()
    mock_tool.name = "t"
    mock_tool.title = "Global Tool Title"
    mock_tool.description = "desc"
    mock_tool.input_schema = {"type": "object"}
    mock_tool.output_schema = None
    mock_tool.annotations = {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "list_tools", AsyncMock(return_value=([mock_tool], None)))

    # Ensure server_id is None
    token = server_id_var.set(None)
    result = await list_tools()
    server_id_var.reset(token)
    assert isinstance(result, list)
    assert result[0].name == "t"
    assert getattr(result[0], "title", None) == "Global Tool Title"
    assert result[0].description == "desc"


@pytest.mark.asyncio
async def test_list_tools_normalizes_null_description(monkeypatch):
    """Test list_tools normalizes null tool descriptions for MCP clients."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_tools, server_id_var, tool_service

    mock_db = MagicMock()
    mock_tool = MagicMock()
    mock_tool.name = "t"
    mock_tool.description = None
    mock_tool.input_schema = {"type": "object"}
    mock_tool.output_schema = None
    mock_tool.annotations = {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "list_tools", AsyncMock(return_value=([mock_tool], None)))

    token = server_id_var.set(None)
    result = await list_tools()
    server_id_var.reset(token)

    assert isinstance(result, list)
    assert result[0].name == "t"
    assert result[0].description == ""


@pytest.mark.asyncio
async def test_list_tools_exception_no_server_id(monkeypatch, caplog):
    """Test list_tools returns [] and logs exception on error when no server_id."""
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


@pytest.mark.asyncio
async def test_list_tools_exception_with_server_id(monkeypatch, caplog):
    """Test list_tools returns [] and logs exception on error when server_id is set."""

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "list_server_tools", AsyncMock(side_effect=Exception("server fail!")))

    # Set authenticated user context to bypass OAuth enforcement
    user_token = user_context_var.set({"is_authenticated": True, "sub": "test@example.com"})
    server_token = server_id_var.set("test-server-id")

    with caplog.at_level("ERROR"):
        result = await list_tools()
        assert result == []
        assert "Error listing tools:server fail!" in caplog.text

    server_id_var.reset(server_token)
    user_context_var.reset(user_token)


# ---------------------------------------------------------------------------
# list_prompts tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_prompts_with_server_id(monkeypatch):
    """Test list_prompts returns prompts for a server_id."""
    # First-Party
    from mcpgateway.schemas import PromptArgument as SchemaPromptArgument

    mock_db = MagicMock()
    mock_prompt = MagicMock()
    mock_prompt.name = "prompt1"
    mock_prompt.title = "Prompt Title"
    mock_prompt.description = "test prompt"
    mock_prompt.arguments = [SchemaPromptArgument(name="arg1", description="desc1", required=False)]

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(prompt_service, "list_server_prompts", AsyncMock(return_value=[mock_prompt]))

    # Set authenticated user context to bypass OAuth enforcement
    user_token = user_context_var.set({"is_authenticated": True, "sub": "test@example.com"})
    server_token = server_id_var.set("test-server")

    result = await list_prompts()
    server_id_var.reset(server_token)
    user_context_var.reset(user_token)

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].name == "prompt1"
    assert getattr(result[0], "title", None) == "Prompt Title"
    assert result[0].description == "test prompt"
    assert len(result[0].arguments) == 1
    assert isinstance(result[0].arguments[0], PromptArgument)
    assert result[0].arguments[0].name == "arg1"
    assert result[0].arguments[0].required is False


@pytest.mark.asyncio
async def test_list_prompts_no_server_id(monkeypatch):
    """Test list_prompts returns prompts when no server_id is set."""
    # First-Party
    from mcpgateway.schemas import PromptArgument as SchemaPromptArgument
    from mcpgateway.transports.streamablehttp_transport import list_prompts, prompt_service, server_id_var

    mock_db = MagicMock()
    mock_prompt = MagicMock()
    mock_prompt.name = "global_prompt"
    mock_prompt.title = "Global Prompt Title"
    mock_prompt.description = "global test prompt"
    mock_prompt.arguments = [SchemaPromptArgument(name="global_arg", description="desc", required=True)]

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(prompt_service, "list_prompts", AsyncMock(return_value=([mock_prompt], None)))

    token = server_id_var.set(None)
    result = await list_prompts()
    server_id_var.reset(token)

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].name == "global_prompt"
    assert getattr(result[0], "title", None) == "Global Prompt Title"
    assert result[0].description == "global test prompt"
    assert len(result[0].arguments) == 1
    assert isinstance(result[0].arguments[0], PromptArgument)
    assert result[0].arguments[0].name == "global_arg"


@pytest.mark.asyncio
async def test_list_prompts_exception_with_server_id(monkeypatch, caplog):
    """Test list_prompts returns [] and logs exception when server_id is set."""

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(prompt_service, "list_server_prompts", AsyncMock(side_effect=Exception("server prompt fail!")))

    # Set authenticated user context to bypass OAuth enforcement
    user_token = user_context_var.set({"is_authenticated": True, "sub": "test@example.com"})
    server_token = server_id_var.set("test-server")

    with caplog.at_level("ERROR"):
        result = await list_prompts()
        assert result == []
        assert "Error listing Prompts:server prompt fail!" in caplog.text

    server_id_var.reset(server_token)
    user_context_var.reset(user_token)


@pytest.mark.asyncio
async def test_list_prompts_exception_no_server_id(monkeypatch, caplog):
    """Test list_prompts returns [] and logs exception when no server_id."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_prompts, prompt_service, server_id_var

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(prompt_service, "list_prompts", AsyncMock(side_effect=Exception("global prompt fail!")))

    token = server_id_var.set(None)
    with caplog.at_level("ERROR"):
        result = await list_prompts()
        assert result == []
        assert "Error listing prompts:global prompt fail!" in caplog.text
    server_id_var.reset(token)


# ---------------------------------------------------------------------------
# get_prompt tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_prompt_success(monkeypatch):
    """Test get_prompt returns prompt result on success."""
    # Third-Party
    from mcp.types import PromptMessage, TextContent

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import get_prompt, prompt_service, types

    mock_db = MagicMock()
    # Create proper PromptMessage structure
    mock_message = PromptMessage(role="user", content=TextContent(type="text", text="test message"))
    mock_result = MagicMock()
    mock_result.messages = [mock_message]
    mock_result.description = "test prompt description"

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(prompt_service, "get_prompt", AsyncMock(return_value=mock_result))

    result = await get_prompt("test_prompt", {"arg1": "value1"})

    assert isinstance(result, types.GetPromptResult)
    assert len(result.messages) == 1
    assert result.description == "test prompt description"


@pytest.mark.asyncio
async def test_get_prompt_no_content(monkeypatch, caplog):
    """Test get_prompt returns [] and logs warning if no content."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import get_prompt, prompt_service

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_result.messages = []

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(prompt_service, "get_prompt", AsyncMock(return_value=mock_result))

    with caplog.at_level("WARNING", logger="mcpgateway.transports.streamablehttp_transport"):
        result = await get_prompt("empty_prompt")
        assert result == []
        assert "No content returned by prompt: empty_prompt" in caplog.text


@pytest.mark.asyncio
async def test_get_prompt_no_result(monkeypatch, caplog):
    """Test get_prompt returns [] and logs warning if no result."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import get_prompt, prompt_service

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(prompt_service, "get_prompt", AsyncMock(return_value=None))

    with caplog.at_level("WARNING", logger="mcpgateway.transports.streamablehttp_transport"):
        result = await get_prompt("missing_prompt")
        assert result == []
        assert "No content returned by prompt: missing_prompt" in caplog.text


@pytest.mark.asyncio
async def test_get_prompt_service_exception(monkeypatch, caplog):
    """Test get_prompt returns [] and logs exception from service."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import get_prompt, prompt_service

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(prompt_service, "get_prompt", AsyncMock(side_effect=Exception("service error!")))

    with caplog.at_level("ERROR"):
        result = await get_prompt("error_prompt")
        assert result == []
        assert "Error getting prompt 'error_prompt': service error!" in caplog.text


@pytest.mark.asyncio
async def test_get_prompt_outer_exception(monkeypatch, caplog):
    """Test get_prompt returns [] and logs exception from outer try-catch."""
    # Standard
    from contextlib import asynccontextmanager

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import get_prompt

    # Cause an exception during get_db context management
    @asynccontextmanager
    async def failing_get_db():
        raise Exception("db error!")
        yield  # pragma: no cover

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", failing_get_db)

    with caplog.at_level("ERROR"):
        result = await get_prompt("db_error_prompt")
        assert result == []
        assert "Error getting prompt 'db_error_prompt': db error!" in caplog.text


# ---------------------------------------------------------------------------
# list_resources tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_resources_with_server_id(monkeypatch):
    """Test list_resources returns resources for a server_id."""

    mock_db = MagicMock()
    mock_resource = MagicMock()
    mock_resource.uri = "file:///test.txt"
    mock_resource.name = "test resource"
    mock_resource.title = "Resource Title"
    mock_resource.description = "test description"
    mock_resource.mime_type = "text/plain"

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(resource_service, "list_server_resources", AsyncMock(return_value=[mock_resource]))

    # Set authenticated user context to bypass OAuth enforcement
    user_token = user_context_var.set({"is_authenticated": True, "sub": "test@example.com"})
    server_token = server_id_var.set("test-server")

    result = await list_resources()

    server_id_var.reset(server_token)
    user_context_var.reset(user_token)

    assert isinstance(result, list)
    assert len(result) == 1
    assert str(result[0].uri) == "file:///test.txt"
    assert result[0].name == "test resource"
    assert getattr(result[0], "title", None) == "Resource Title"
    assert result[0].description == "test description"


@pytest.mark.asyncio
async def test_list_resources_no_server_id(monkeypatch):
    """Test list_resources returns resources when no server_id is set."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_resources, resource_service, server_id_var

    mock_db = MagicMock()
    mock_resource = MagicMock()
    mock_resource.uri = "http://example.com/resource"
    mock_resource.name = "global resource"
    mock_resource.title = "Global Resource Title"
    mock_resource.description = "global description"
    mock_resource.mime_type = "application/json"

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(resource_service, "list_resources", AsyncMock(return_value=([mock_resource], None)))

    token = server_id_var.set(None)
    result = await list_resources()
    server_id_var.reset(token)

    assert isinstance(result, list)
    assert len(result) == 1
    assert str(result[0].uri) == "http://example.com/resource"
    assert getattr(result[0], "title", None) == "Global Resource Title"
    assert result[0].name == "global resource"


@pytest.mark.asyncio
async def test_list_resources_exception_with_server_id(monkeypatch, caplog):
    """Test list_resources returns [] and logs exception when server_id is set."""

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(resource_service, "list_server_resources", AsyncMock(side_effect=Exception("server resource fail!")))

    # Set authenticated user context to bypass OAuth enforcement
    user_token = user_context_var.set({"is_authenticated": True, "sub": "test@example.com"})
    server_token = server_id_var.set("test-server")

    with caplog.at_level("ERROR"):
        result = await list_resources()
        assert result == []
        assert "Error listing Resources:server resource fail!" in caplog.text

    server_id_var.reset(server_token)
    user_context_var.reset(user_token)


@pytest.mark.asyncio
async def test_list_resources_exception_no_server_id(monkeypatch, caplog):
    """Test list_resources returns [] and logs exception when no server_id."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_resources, resource_service, server_id_var

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(resource_service, "list_resources", AsyncMock(side_effect=Exception("global resource fail!")))

    token = server_id_var.set(None)
    with caplog.at_level("ERROR"):
        result = await list_resources()
        assert result == []
        assert "Error listing resources:global resource fail!" in caplog.text
    server_id_var.reset(token)


# ---------------------------------------------------------------------------
# list_resource_templates tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_resource_templates_public_only_token(monkeypatch):
    """Test list_resource_templates passes empty token_teams for public-only access."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_resource_templates, resource_service, server_id_var, user_context_var

    mock_db = MagicMock()
    mock_template = MagicMock()
    mock_template.model_dump = MagicMock(return_value={"uri_template": "file:///{path}", "name": "Files"})

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    # Track what parameters were passed to the service
    captured_calls = []

    async def mock_list_templates(db, user_email=None, token_teams=None, server_id=None):
        captured_calls.append({"user_email": user_email, "token_teams": token_teams, "server_id": server_id})
        return [mock_template]

    monkeypatch.setattr(resource_service, "list_resource_templates", mock_list_templates)

    # Set public-only user context (no auth, teams=None which becomes [])
    user_token = user_context_var.set({"email": None, "teams": None, "is_admin": False, "is_authenticated": True})
    server_token = server_id_var.set("test-server")
    try:
        result = await list_resource_templates()
    finally:
        user_context_var.reset(user_token)
        server_id_var.reset(server_token)

    # Verify the service was called with public-only access (empty teams)
    assert len(captured_calls) == 1
    assert captured_calls[0]["user_email"] is None
    assert captured_calls[0]["token_teams"] == []  # Public-only (secure default)
    assert captured_calls[0]["server_id"] == "test-server"

    assert isinstance(result, list)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_list_resource_templates_admin_unrestricted(monkeypatch):
    """Test list_resource_templates passes token_teams=None for admin users without team restrictions."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_resource_templates, resource_service, server_id_var, user_context_var

    mock_db = MagicMock()
    mock_template = MagicMock()
    mock_template.model_dump = MagicMock(return_value={"uri_template": "file:///{path}", "name": "Files"})

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    captured_calls = []

    async def mock_list_templates(db, user_email=None, token_teams=None, server_id=None):
        captured_calls.append({"user_email": user_email, "token_teams": token_teams, "server_id": server_id})
        return [mock_template]

    monkeypatch.setattr(resource_service, "list_resource_templates", mock_list_templates)

    # Set admin user context with no team restrictions
    user_token = user_context_var.set({"email": "admin@example.com", "teams": None, "is_admin": True, "is_authenticated": True})
    server_token = server_id_var.set("test-server")
    try:
        result = await list_resource_templates()
    finally:
        user_context_var.reset(user_token)
        server_id_var.reset(server_token)

    # Verify the service was called with admin unrestricted access
    assert len(captured_calls) == 1
    assert captured_calls[0]["user_email"] is None  # Admin bypass clears email
    assert captured_calls[0]["token_teams"] is None  # Unrestricted
    assert captured_calls[0]["server_id"] == "test-server"

    assert isinstance(result, list)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_list_resource_templates_team_scoped(monkeypatch):
    """Test list_resource_templates passes token_teams for team-scoped access."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_resource_templates, resource_service, server_id_var, user_context_var

    mock_db = MagicMock()
    mock_template = MagicMock()
    mock_template.model_dump = MagicMock(return_value={"uri_template": "file:///{path}", "name": "Files"})

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    captured_calls = []

    async def mock_list_templates(db, user_email=None, token_teams=None, server_id=None):
        captured_calls.append({"user_email": user_email, "token_teams": token_teams, "server_id": server_id})
        return [mock_template]

    monkeypatch.setattr(resource_service, "list_resource_templates", mock_list_templates)

    # Set user context with specific team membership
    user_token = user_context_var.set({"email": "user@example.com", "teams": ["team-1", "team-2"], "is_admin": False, "is_authenticated": True})
    server_token = server_id_var.set("test-server")
    try:
        result = await list_resource_templates()
    finally:
        user_context_var.reset(user_token)
        server_id_var.reset(server_token)

    # Verify the service was called with team-scoped access
    assert len(captured_calls) == 1
    assert captured_calls[0]["user_email"] == "user@example.com"
    assert captured_calls[0]["token_teams"] == ["team-1", "team-2"]
    assert captured_calls[0]["server_id"] == "test-server"

    assert isinstance(result, list)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# read_resource tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_resource_success(monkeypatch):
    """Test read_resource returns resource content on success."""
    # Third-Party
    from pydantic import AnyUrl

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import read_resource, resource_service

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_result.text = "resource content here"
    mock_result.blob = None  # Explicitly set to None so text is returned

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(resource_service, "read_resource", AsyncMock(return_value=mock_result))

    test_uri = AnyUrl("file:///test.txt")
    result = await read_resource(test_uri)

    assert result == "resource content here"


@pytest.mark.asyncio
async def test_read_resource_no_content(monkeypatch, caplog):
    """Test read_resource returns empty string and logs warning if no content."""
    # Third-Party
    from pydantic import AnyUrl

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import read_resource, resource_service

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_result.text = ""
    mock_result.blob = None

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(resource_service, "read_resource", AsyncMock(return_value=mock_result))

    test_uri = AnyUrl("file:///empty.txt")
    with caplog.at_level("WARNING", logger="mcpgateway.transports.streamablehttp_transport"):
        result = await read_resource(test_uri)
        assert result == ""
        assert "No content returned by resource: file:///empty.txt" in caplog.text


@pytest.mark.asyncio
async def test_read_resource_no_result(monkeypatch, caplog):
    """Test read_resource returns empty string and logs warning if no result."""
    # Third-Party
    from pydantic import AnyUrl

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import read_resource, resource_service

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(resource_service, "read_resource", AsyncMock(return_value=None))

    test_uri = AnyUrl("file:///missing.txt")
    with caplog.at_level("WARNING", logger="mcpgateway.transports.streamablehttp_transport"):
        result = await read_resource(test_uri)
        assert result == ""
        assert "No content returned by resource: file:///missing.txt" in caplog.text


@pytest.mark.asyncio
async def test_read_resource_service_exception(monkeypatch, caplog):
    """Test read_resource returns empty string and logs exception from service."""
    # Third-Party
    from pydantic import AnyUrl

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import read_resource, resource_service

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(resource_service, "read_resource", AsyncMock(side_effect=Exception("service error!")))

    test_uri = AnyUrl("file:///error.txt")
    with caplog.at_level("ERROR"):
        result = await read_resource(test_uri)
        assert result == ""
        assert "Error reading resource 'file:///error.txt': service error!" in caplog.text


@pytest.mark.asyncio
async def test_read_resource_outer_exception(monkeypatch, caplog):
    """Test read_resource returns empty string and logs exception from outer try-catch."""
    # Standard
    from contextlib import asynccontextmanager

    # Third-Party
    from pydantic import AnyUrl

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import read_resource

    # Cause an exception during get_db context management
    @asynccontextmanager
    async def failing_get_db():
        raise Exception("db error!")
        yield  # pragma: no cover

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", failing_get_db)

    test_uri = AnyUrl("file:///db_error.txt")
    with caplog.at_level("ERROR"):
        result = await read_resource(test_uri)
        assert result == ""
        assert "Error reading resource 'file:///db_error.txt': db error!" in caplog.text


# ---------------------------------------------------------------------------
# streamable_http_auth tests
# ---------------------------------------------------------------------------


# def _make_scope(path: str, headers: list[tuple[bytes, bytes]] | None = None) -> Scope:  # helper
#     return {
#         "type": "http",
#         "path": path,
#         "headers": headers or [],
#     }


def _make_scope(path: str, headers: list[tuple[bytes, bytes]] | None = None, method: str = "POST", client: tuple[str, int] | None = ("127.0.0.1", 0)) -> Scope:
    scope: dict = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers or [],
        "modified_path": path,
        "scheme": "https",
        "server": ("localhost", 4444),
    }
    if client is not None:
        scope["client"] = client
    return scope


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
        raise HTTPException(status_code=401, detail="bad token")

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
async def test_streamable_http_auth_skips_well_known_rfc9728_even_when_strict(monkeypatch):
    """RFC 9728 well-known metadata paths should bypass MCP auth gate."""
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", True)
    scope = _make_scope("/.well-known/oauth-protected-resource/servers/550e8400-e29b-41d4-a716-446655440000/mcp")
    called = []

    async def send(msg):
        called.append(msg)

    result = await streamable_http_auth(scope, None, send)
    assert result is True
    assert called == []


@pytest.mark.asyncio
async def test_streamable_http_auth_requires_auth_for_mcp_sse(monkeypatch):
    """Auth should require authentication for /mcp/sse paths."""
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", True)
    scope = _make_scope("/mcp/sse")
    called = []

    async def send(msg):
        called.append(msg)

    result = await streamable_http_auth(scope, None, send)
    assert result is False
    assert len(called) == 2  # http.response.start + http.response.body
    assert called[0]["type"] == "http.response.start"
    assert called[0]["status"] == 401
    assert called[1]["type"] == "http.response.body"
    assert b"Authentication required" in called[1]["body"]


@pytest.mark.asyncio
async def test_streamable_http_auth_requires_auth_for_mcp_message(monkeypatch):
    """Auth should require authentication for /mcp/message paths."""
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", True)
    scope = _make_scope("/mcp/message")
    called = []

    async def send(msg):
        called.append(msg)

    result = await streamable_http_auth(scope, None, send)
    assert result is False
    assert len(called) == 2  # http.response.start + http.response.body
    assert called[0]["type"] == "http.response.start"
    assert called[0]["status"] == 401
    assert called[1]["type"] == "http.response.body"
    assert b"Authentication required" in called[1]["body"]


@pytest.mark.asyncio
async def test_streamable_http_auth_requires_auth_for_servers_mcp_sse(monkeypatch):
    """Auth should require authentication for /servers/{id}/mcp/sse paths."""
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", True)
    monkeypatch.setattr(tr, "_check_server_oauth_enforcement", AsyncMock(return_value=None))
    scope = _make_scope("/servers/test-server-id/mcp/sse")
    called = []

    async def send(msg):
        called.append(msg)

    result = await streamable_http_auth(scope, None, send)
    assert result is False
    assert len(called) == 2  # http.response.start + http.response.body
    assert called[0]["type"] == "http.response.start"
    assert called[0]["status"] == 401
    assert called[1]["type"] == "http.response.body"
    assert b"Authentication required" in called[1]["body"]


@pytest.mark.asyncio
async def test_streamable_http_auth_requires_auth_for_servers_mcp_message(monkeypatch):
    """Auth should require authentication for /servers/{id}/mcp/message paths."""
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", True)
    monkeypatch.setattr(tr, "_check_server_oauth_enforcement", AsyncMock(return_value=None))
    scope = _make_scope("/servers/test-server-id/mcp/message")
    called = []

    async def send(msg):
        called.append(msg)

    result = await streamable_http_auth(scope, None, send)
    assert result is False
    assert len(called) == 2  # http.response.start + http.response.body
    assert called[0]["type"] == "http.response.start"
    assert called[0]["status"] == 401
    assert called[1]["type"] == "http.response.body"
    assert b"Authentication required" in called[1]["body"]


@pytest.mark.asyncio
async def test_streamable_http_auth_allows_mcp_sse_with_valid_token(monkeypatch):
    """Auth should allow /mcp/sse with valid Bearer token."""
    # Standard
    from unittest.mock import patch

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.auth_cache_batch_queries", False)

    async def fake_verify(token):
        return {"sub": "admin@example.com", "teams": None, "is_admin": True}

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    scope = _make_scope("/mcp/sse", headers=[(b"authorization", b"Bearer valid-token")])
    called = []

    async def send(msg):
        called.append(msg)

    with (
        patch("mcpgateway.cache.auth_cache.get_auth_cache", return_value=None),
        patch("mcpgateway.auth._get_user_by_email_sync", return_value=None),
        patch("mcpgateway.auth._check_token_revoked_sync", return_value=False),
    ):
        result = await streamable_http_auth(scope, None, send)

    assert result is True
    assert called == []


@pytest.mark.asyncio
async def test_streamable_http_auth_allows_mcp_message_with_valid_token(monkeypatch):
    """Auth should allow /mcp/message with valid Bearer token."""
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.auth_cache_batch_queries", False)

    async def fake_verify(token):
        return {"sub": "admin@example.com", "teams": None, "is_admin": True}

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    scope = _make_scope("/mcp/message", headers=[(b"authorization", b"Bearer valid-token")])
    called = []

    async def send(msg):
        called.append(msg)

    with (
        patch("mcpgateway.cache.auth_cache.get_auth_cache", return_value=None),
        patch("mcpgateway.auth._get_user_by_email_sync", return_value=None),
        patch("mcpgateway.auth._check_token_revoked_sync", return_value=False),
    ):
        result = await streamable_http_auth(scope, None, send)

    assert result is True
    assert called == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/mcp/sse/", "/mcp/message/", "/servers/test-id/mcp/sse/", "/servers/test-id/mcp/message/"])
async def test_streamable_http_auth_requires_auth_for_trailing_slash_variants(monkeypatch, path):
    """Auth must not be bypassed by appending a trailing slash to MCP transport paths."""
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", True)
    monkeypatch.setattr(tr, "_check_server_oauth_enforcement", AsyncMock(return_value=None))
    scope = _make_scope(path)
    called = []

    async def send(msg):
        called.append(msg)

    result = await streamable_http_auth(scope, None, send)
    assert result is False, f"Path {path} should require auth but was allowed through"
    assert called[0]["status"] == 401


@pytest.mark.asyncio
async def test_streamable_http_auth_skips_cors_preflight():
    """Auth returns True for CORS preflight requests (OPTIONS with Origin and Access-Control-Request-Method)."""
    # CORS preflight requests cannot carry Authorization headers, so they must be exempt from auth
    # A proper preflight has: OPTIONS method + Origin header + Access-Control-Request-Method header
    # See: https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS#preflighted_requests
    scope = _make_scope(
        "/servers/1/mcp",
        method="OPTIONS",
        headers=[
            (b"origin", b"http://localhost:3000"),
            (b"access-control-request-method", b"POST"),
        ],
    )
    called = []

    async def send(msg):
        called.append(msg)

    result = await streamable_http_auth(scope, None, send)
    assert result is True
    assert called == []  # No response sent - auth skipped entirely


@pytest.mark.asyncio
async def test_streamable_http_auth_requires_auth_for_options_without_cors_headers(monkeypatch):
    """OPTIONS without CORS preflight headers still requires auth (not a true preflight)."""
    # Enable strict auth mode to verify non-preflight OPTIONS still goes through normal auth
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", True)
    # Stub per-server OAuth check — this test validates OPTIONS handling, not OAuth
    monkeypatch.setattr(tr, "_check_server_oauth_enforcement", AsyncMock(return_value=None))

    # OPTIONS request without Origin or Access-Control-Request-Method is NOT a CORS preflight
    scope = _make_scope("/servers/1/mcp", method="OPTIONS")
    called = []

    async def send(msg):
        called.append(msg)

    result = await streamable_http_auth(scope, None, send)
    # Should fail auth since no Authorization header and it's not a CORS preflight
    assert result is False
    assert called and called[0]["type"] == "http.response.start"
    assert called[0]["status"] == tr.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_streamable_http_auth_no_authorization_strict_mode(monkeypatch):
    """Auth returns False and sends 401 if no Authorization header when mcp_require_auth=True."""
    # Enable strict auth mode to test 401 behavior
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", True)
    # Stub per-server OAuth check — this test validates strict-mode 401, not per-server OAuth
    monkeypatch.setattr(tr, "_check_server_oauth_enforcement", AsyncMock(return_value=None))

    scope = _make_scope("/servers/1/mcp")
    called = []

    async def send(msg):
        called.append(msg)

    result = await streamable_http_auth(scope, None, send)
    assert result is False
    assert called and called[0]["type"] == "http.response.start"
    assert called[0]["status"] == tr.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_streamable_http_auth_no_authorization_permissive_mode(monkeypatch):
    """Auth allows unauthenticated requests with public-only access when mcp_require_auth=False."""
    # Ensure permissive mode (default)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", False)
    # Stub out per-server OAuth check — this test validates permissive-mode plumbing, not OAuth
    monkeypatch.setattr(tr, "_check_server_oauth_enforcement", AsyncMock(return_value=None))

    scope = _make_scope("/servers/1/mcp")
    called = []

    async def send(msg):
        called.append(msg)

    result = await streamable_http_auth(scope, None, send)
    assert result is True  # Allowed through
    assert called == []  # No 401 sent

    # Verify user context was set with public-only access
    user_ctx = tr.user_context_var.get()
    assert user_ctx.get("email") is None
    assert user_ctx.get("teams") == []  # Public-only
    assert user_ctx.get("is_authenticated") is False


# --- Auth bypass regression tests for /mcp/{server_id} (Fixes #3752, #3812) ---


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/mcp/abc123def", "/mcp/test", "/mcp/../admin", "/mcp/nonexistent-id"])
async def test_streamable_http_auth_rejects_undocumented_mcp_subpaths(monkeypatch, path):
    """Regression: undocumented /mcp/* sub-paths are rejected with 404.

    Before fix, the auth gate only matched paths ending with /mcp. Since
    /mcp/{server_id} ends with the server ID (not /mcp), authenticate()
    returned True immediately — skipping ALL auth and serving tools via an
    undocumented global alias.  Now these paths are rejected as 404 regardless
    of auth mode, since /mcp/{id} is not a valid endpoint.  (Fixes #3812)
    """
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", True)

    scope = _make_scope(path)
    called = []

    async def send(msg):
        called.append(msg)

    result = await streamable_http_auth(scope, None, send)
    assert result is False
    assert called and called[0]["type"] == "http.response.start"
    assert called[0]["status"] == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/mcp/abc123def", "/mcp/test"])
async def test_streamable_http_auth_rejects_undocumented_mcp_subpaths_permissive(monkeypatch, path):
    """Undocumented /mcp/* sub-paths rejected even in permissive mode (not an auth bypass)."""
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", False)

    scope = _make_scope(path)
    called = []

    async def send(msg):
        called.append(msg)

    result = await streamable_http_auth(scope, None, send)
    assert result is False
    assert called[0]["status"] == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/mcp/../admin",  # Uvicorn decodes %2e%2e → .. before scope["path"]
        "/mcp/./hidden",  # single-dot segment
        "/mcp//message",  # double-slash (NOT the same as /mcp/message)
        "/mcp/ ",  # trailing space
    ],
)
async def test_streamable_http_auth_rejects_decoded_path_traversal_variants(monkeypatch, path):
    """Defense-in-depth: percent-decoded path variants must still be rejected.

    Uvicorn percent-decodes scope["path"] before our code runs (e.g.
    /mcp/%2e%2e/admin becomes /mcp/../admin).  These tests verify the
    allowlist check is not bypassed by decoded traversal sequences.
    """
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", True)

    scope = _make_scope(path)
    called = []

    async def send(msg):
        called.append(msg)

    result = await streamable_http_auth(scope, None, send)
    assert result is False
    assert called and called[0]["status"] == 404


@pytest.mark.asyncio
async def test_streamable_http_auth_oauth_server_returns_resource_metadata_in_strict_mode(monkeypatch):
    """Per-server OAuth runs before global strict-mode check so resource_metadata is included.

    Before fix, strict mode (mcp_require_auth=True) returned a generic
    WWW-Authenticate: Bearer without resource_metadata URL, preventing
    MCP clients from discovering the OAuth server.  (Fixes #3752)
    """
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", True)

    mock_server = MagicMock()
    mock_server.oauth_enabled = True

    mock_db = MagicMock()
    mock_db.execute.return_value.scalar_one_or_none.return_value = mock_server

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", _make_fake_get_db(mock_db))

    scope = _make_scope("/servers/abc123def/mcp")
    called = []

    async def send(msg):
        called.append(msg)

    token = tr._oauth_checked_var.set(False)
    try:
        result = await streamable_http_auth(scope, None, send)
    finally:
        tr._oauth_checked_var.reset(token)
    assert result is False
    assert called[0]["status"] == 401
    # Key assertion: resource_metadata URL must be present even in strict mode
    www_auth = dict(called[0].get("headers", [])).get(b"www-authenticate", b"").decode()
    assert "resource_metadata=" in www_auth


@pytest.mark.asyncio
async def test_streamable_http_auth_wrong_scheme(monkeypatch):
    """Auth returns False and sends 401 if Authorization is not Bearer and mcp_require_auth=True."""

    async def fake_verify(token):
        raise AssertionError("Should not be called")

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)
    # Enable strict auth mode to test 401 behavior
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", True)
    # Stub per-server OAuth check — this test validates scheme rejection, not OAuth
    monkeypatch.setattr(tr, "_check_server_oauth_enforcement", AsyncMock(return_value=None))
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
    """Auth returns False and sends 401 if Bearer but no token and mcp_require_auth=True."""

    async def fake_verify(token):
        raise AssertionError("Should not be called")

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)
    # Enable strict auth mode to test 401 behavior
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", True)
    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer")])
    called = []

    async def send(msg):
        called.append(msg)

    result = await streamable_http_auth(scope, None, send)
    assert result is False
    assert called and called[0]["type"] == "http.response.start"
    assert called[0]["status"] == tr.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_streamable_http_auth_bearer_no_token_permissive_mode(monkeypatch):
    """Bearer-without-token should still return 401 when mcp_require_auth=False."""

    async def fake_verify(token):
        raise AssertionError("Should not be called")

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", False)
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
async def test_session_manager_wrapper_initialization_stateful(monkeypatch):
    """Test SessionManagerWrapper initialization with stateful sessions enabled."""
    # Standard
    from contextlib import asynccontextmanager

    class DummySessionManager:
        def __init__(self, **kwargs):
            self.config = kwargs

        @asynccontextmanager
        async def run(self):
            yield self

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def handle_request(self, scope, receive, send):
            self.called = True

    captured_config = {}

    def capture_manager(**kwargs):
        captured_config.update(kwargs)
        return DummySessionManager(**kwargs)

    # Mock settings to enable stateful sessions with InMemoryEventStore
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.json_response_enabled", False)
    # Ensure InMemoryEventStore is used (not Redis) by clearing Redis settings
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.cache_type", "memory")
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.redis_url", "")
    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", capture_manager)

    wrapper = SessionManagerWrapper()

    # Verify that stateful configuration was used
    assert captured_config["stateless"] is False
    assert captured_config["event_store"] is not None
    assert isinstance(captured_config["event_store"], tr.InMemoryEventStore)

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
        def __init__(self):
            self._server_instances = {}  # Add _server_instances attribute

        @asynccontextmanager
        async def run(self):
            yield self

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def handle_request(self, scope, receive, send_func):
            self.called = True
            # Send proper ASGI messages
            await send_func({"type": "http.response.start", "status": 200, "headers": []})
            await send_func({"type": "http.response.body", "body": b"ok"})

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    wrapper = SessionManagerWrapper()
    await wrapper.initialize()
    scope = _make_scope("/servers/123/mcp")
    sent = []
    await wrapper.handle_streamable_http(scope, None, send)
    await wrapper.shutdown()
    # Verify proper ASGI messages were sent
    assert len(sent) == 2
    assert sent[0]["type"] == "http.response.start"
    assert sent[1]["type"] == "http.response.body"


@pytest.mark.asyncio
async def test_session_manager_wrapper_handle_streamable_http_no_server_id(monkeypatch):
    """Test handle_streamable_http without server_id match in path."""
    # Standard
    from contextlib import asynccontextmanager

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import server_id_var

    async def send(msg):
        sent.append(msg)

    class DummySessionManager:
        def __init__(self):
            self._server_instances = {}  # Add _server_instances attribute

        @asynccontextmanager
        async def run(self):
            yield self

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def handle_request(self, scope, receive, send_func):
            self.called = True
            # Check that server_id was set to None
            assert server_id_var.get() is None
            # Send proper ASGI messages
            await send_func({"type": "http.response.start", "status": 200, "headers": []})
            await send_func({"type": "http.response.body", "body": b"ok_no_server"})

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    wrapper = SessionManagerWrapper()
    await wrapper.initialize()
    # Use a path that doesn't match the server_id pattern
    scope = _make_scope("/some/other/path")
    sent = []
    await wrapper.handle_streamable_http(scope, None, send)
    await wrapper.shutdown()
    # Verify proper ASGI messages were sent
    assert len(sent) == 2
    assert sent[0]["type"] == "http.response.start"
    assert sent[1]["type"] == "http.response.body"


@pytest.mark.asyncio
async def test_session_manager_wrapper_handle_streamable_http_exception(monkeypatch, caplog):
    """Test handle_streamable_http returns 503 when server validation fails."""
    # Standard
    from contextlib import asynccontextmanager

    class DummySessionManager:
        def __init__(self):
            self._server_instances = {}  # Add _server_instances attribute

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

    # Track what was sent
    sent_messages = []

    async def send(msg):
        sent_messages.append(msg)

    # The new validation will catch the database error and return 503
    # before the RuntimeError from handle_request is reached
    await wrapper.handle_streamable_http(scope, None, send)
    await wrapper.shutdown()

    # Verify 503 response was sent due to server validation failure
    assert len(sent_messages) >= 2
    assert sent_messages[0]["type"] == "http.response.start"
    assert sent_messages[0]["status"] == 503
    assert "Failed to validate server ID" in caplog.text


# ---------------------------------------------------------------------------
# Ring buffer and per-stream sequence tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_store_sequence_per_stream():
    """Per-stream sequence numbers should be independent across streams."""
    store = InMemoryEventStore(max_events_per_stream=10)
    eid1 = await store.store_event("s1", {"id": 1})  # seq 0 for s1
    eid2 = await store.store_event("s2", {"id": 2})  # seq 0 for s2
    eid3 = await store.store_event("s1", {"id": 3})  # seq 1 for s1

    assert store.event_index[eid1].seq_num == 0
    assert store.event_index[eid2].seq_num == 0  # Different stream, same seq
    assert store.event_index[eid3].seq_num == 1


@pytest.mark.asyncio
async def test_event_store_replay_wraps_ring():
    """Replay should work correctly after ring buffer wrap-around."""
    store = InMemoryEventStore(max_events_per_stream=3)
    stream_id = "wrap"
    # Store 5 events; first 2 will be evicted
    ids = [await store.store_event(stream_id, {"id": i}) for i in range(5)]
    sent: List[tr.EventMessage] = []

    async def collector(msg):
        sent.append(msg)

    # Replay after event at index 2 (id=2), should get events 3 and 4
    await store.replay_events_after(ids[2], collector)
    assert [msg.message["id"] for msg in sent] == [3, 4]


@pytest.mark.asyncio
async def test_event_store_interleaved_streams():
    """Interleaved storage across streams should not affect replay correctness."""
    store = InMemoryEventStore(max_events_per_stream=5)
    # Interleave events across two streams
    s1_ids = []
    s2_ids = []
    for i in range(4):
        s1_ids.append(await store.store_event("s1", {"stream": "s1", "idx": i}))
        s2_ids.append(await store.store_event("s2", {"stream": "s2", "idx": i}))

    # Replay s1 from event 1 (should get events 2, 3)
    s1_sent: List[tr.EventMessage] = []

    async def s1_collector(msg):
        s1_sent.append(msg)

    result = await store.replay_events_after(s1_ids[1], s1_collector)
    assert result == "s1"
    assert len(s1_sent) == 2
    assert [m.message["idx"] for m in s1_sent] == [2, 3]

    # Replay s2 from event 0 (should get events 1, 2, 3)
    s2_sent: List[tr.EventMessage] = []

    async def s2_collector(msg):
        s2_sent.append(msg)

    result = await store.replay_events_after(s2_ids[0], s2_collector)
    assert result == "s2"
    assert len(s2_sent) == 3
    assert [m.message["idx"] for m in s2_sent] == [1, 2, 3]


@pytest.mark.asyncio
async def test_event_store_evicted_event_returns_none():
    """Replaying from an evicted event should return None."""
    store = InMemoryEventStore(max_events_per_stream=2)
    eid1 = await store.store_event("s", {"id": 1})
    await store.store_event("s", {"id": 2})
    await store.store_event("s", {"id": 3})  # Evicts eid1

    sent: List[tr.EventMessage] = []

    async def collector(msg):
        sent.append(msg)

    # eid1 is no longer in event_index
    result = await store.replay_events_after(eid1, collector)
    assert result is None
    assert sent == []


@pytest.mark.asyncio
async def test_event_store_last_event_in_stream():
    """Replaying from the last event should return stream_id with no events."""
    store = InMemoryEventStore(max_events_per_stream=10)
    await store.store_event("s", {"id": 1})
    eid2 = await store.store_event("s", {"id": 2})

    sent: List[tr.EventMessage] = []

    async def collector(msg):
        sent.append(msg)

    result = await store.replay_events_after(eid2, collector)
    assert result == "s"
    assert sent == []  # No events after the last one


@pytest.mark.asyncio
async def test_stream_buffer_len():
    """StreamBuffer.__len__ should return the count of events."""
    buffer = tr.StreamBuffer(entries=[None, None, None])
    assert len(buffer) == 0
    buffer.count = 2
    assert len(buffer) == 2


# ---------------------------------------------------------------------------
# Token Teams Context Tests (Issue #1915)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streamable_http_auth_sets_user_context_with_teams(monkeypatch):
    """Auth sets user context with email, teams, and is_admin from JWT payload."""
    # Standard
    from unittest.mock import MagicMock, patch

    async def fake_verify(token):
        return {
            "sub": "user@example.com",
            "teams": ["team_a", "team_b"],
            "user": {"is_admin": True},
        }

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    # Mock auth_cache to return valid membership (skip DB lookup)
    mock_auth_cache = MagicMock()
    mock_auth_cache.get_team_membership_valid_sync.return_value = True

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer good-token")])
    messages = []

    async def send(msg):
        messages.append(msg)

    with patch("mcpgateway.cache.auth_cache.get_auth_cache", return_value=mock_auth_cache):
        result = await streamable_http_auth(scope, None, send)

    assert result is True
    assert len(messages) == 0  # Should not send 401

    # Verify user context was set correctly
    user_ctx = tr.user_context_var.get()
    assert user_ctx.get("email") == "user@example.com"
    assert user_ctx.get("teams") == ["team_a", "team_b"]
    assert user_ctx.get("is_admin") is True
    assert user_ctx.get("is_authenticated") is True


@pytest.mark.asyncio
async def test_streamable_http_auth_normalizes_dict_teams(monkeypatch):
    """Auth normalizes team dicts to string IDs."""
    # Standard
    from unittest.mock import MagicMock, patch

    async def fake_verify(token):
        return {
            "sub": "user@example.com",
            "teams": [{"id": "t1", "name": "Team 1"}, {"id": "t2", "name": "Team 2"}],
            "user": {"is_admin": False},
        }

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    # Mock auth_cache to return valid membership (skip DB lookup)
    mock_auth_cache = MagicMock()
    mock_auth_cache.get_team_membership_valid_sync.return_value = True

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer good-token")])

    async def send(msg):
        pass

    with patch("mcpgateway.cache.auth_cache.get_auth_cache", return_value=mock_auth_cache):
        result = await streamable_http_auth(scope, None, send)

    assert result is True

    # Verify teams were normalized to IDs
    user_ctx = tr.user_context_var.get()
    assert user_ctx.get("teams") == ["t1", "t2"]


@pytest.mark.asyncio
async def test_streamable_http_auth_handles_empty_teams(monkeypatch):
    """Auth handles empty teams list correctly."""

    async def fake_verify(token):
        return {
            "sub": "user@example.com",
            "teams": [],
            "user": {},
        }

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer good-token")])

    async def send(msg):
        pass

    result = await streamable_http_auth(scope, None, send)

    assert result is True

    user_ctx = tr.user_context_var.get()
    assert user_ctx.get("email") == "user@example.com"
    assert user_ctx.get("teams") == []
    assert user_ctx.get("is_admin") is False


@pytest.mark.asyncio
async def test_streamable_http_auth_uses_email_field_fallback(monkeypatch):
    """Auth uses email field when sub is not present."""
    # Standard
    from unittest.mock import MagicMock, patch

    async def fake_verify(token):
        return {
            "email": "email_user@example.com",  # Only email, no sub
            "teams": ["team_x"],
        }

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    # Mock auth_cache to return valid membership (skip DB lookup)
    mock_auth_cache = MagicMock()
    mock_auth_cache.get_team_membership_valid_sync.return_value = True

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer good-token")])

    async def send(msg):
        pass

    with patch("mcpgateway.cache.auth_cache.get_auth_cache", return_value=mock_auth_cache):
        result = await streamable_http_auth(scope, None, send)

    assert result is True

    user_ctx = tr.user_context_var.get()
    assert user_ctx.get("email") == "email_user@example.com"


@pytest.mark.asyncio
async def test_streamable_http_auth_handles_missing_teams_key(monkeypatch):
    """Auth handles JWT payload without teams key - returns None for unrestricted access."""

    async def fake_verify(token):
        return {
            "sub": "user@example.com",
            # No teams key - legacy token without team scoping
        }

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer good-token")])

    async def send(msg):
        pass

    result = await streamable_http_auth(scope, None, send)

    assert result is True

    user_ctx = tr.user_context_var.get()
    assert user_ctx.get("teams") == []  # [] = public-only (missing teams key = secure default)


@pytest.mark.asyncio
async def test_streamable_http_auth_rejects_removed_team_member(monkeypatch):
    """Auth rejects tokens for users no longer in the team (cached rejection)."""
    # Standard
    from unittest.mock import MagicMock, patch

    async def fake_verify(token):
        return {
            "sub": "removed_user@example.com",
            "teams": ["team_a"],
        }

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    # Mock auth_cache to return False (user was removed from team)
    mock_auth_cache = MagicMock()
    mock_auth_cache.get_team_membership_valid_sync.return_value = False

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer valid-but-stale-token")])
    sent = []

    async def send(msg):
        sent.append(msg)

    with patch("mcpgateway.cache.auth_cache.get_auth_cache", return_value=mock_auth_cache):
        result = await streamable_http_auth(scope, None, send)

    # Should reject with 403
    assert result is False
    assert sent and sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 403


@pytest.mark.asyncio
async def test_streamable_http_auth_validates_team_membership_on_cache_miss(monkeypatch):
    """Auth validates team membership via DB when cache misses."""
    # Standard
    from unittest.mock import MagicMock, patch

    async def fake_verify(token):
        return {
            "sub": "user@example.com",
            "teams": ["team_a", "team_b"],
        }

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    # Mock auth_cache to return None (cache miss)
    mock_auth_cache = MagicMock()
    mock_auth_cache.get_team_membership_valid_sync.return_value = None
    mock_auth_cache.set_team_membership_valid_sync = MagicMock()

    # Mock DB to return only team_a membership (missing team_b)
    mock_db = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = ["team_a"]  # Only member of team_a, not team_b
    mock_execute = MagicMock()
    mock_execute.scalars.return_value = mock_scalars
    mock_db.execute.return_value = mock_execute

    mock_session_local = MagicMock()
    mock_session_local.return_value.__enter__ = MagicMock(return_value=mock_db)
    mock_session_local.return_value.__exit__ = MagicMock(return_value=False)

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer token")])
    sent = []

    async def send(msg):
        sent.append(msg)

    with (
        patch("mcpgateway.cache.auth_cache.get_auth_cache", return_value=mock_auth_cache),
        patch("mcpgateway.transports.streamablehttp_transport.SessionLocal", mock_session_local),
    ):
        result = await streamable_http_auth(scope, None, send)

    # Should reject with 403 because user is not in team_b
    assert result is False
    assert sent and sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 403

    # Should have cached the negative result
    mock_auth_cache.set_team_membership_valid_sync.assert_called_once_with("user@example.com", ["team_a", "team_b"], False)


@pytest.mark.asyncio
async def test_streamable_http_auth_handles_null_teams(monkeypatch):
    """Auth handles JWT payload with teams: null - same as missing teams key."""

    async def fake_verify(token):
        return {
            "sub": "user@example.com",
            "teams": None,  # Explicit null - treated same as missing
        }

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer good-token")])

    async def send(msg):
        pass

    result = await streamable_http_auth(scope, None, send)

    assert result is True

    user_ctx = tr.user_context_var.get()
    assert user_ctx.get("teams") == []  # [] = public-only (null without is_admin = secure default)


@pytest.mark.asyncio
async def test_streamable_http_auth_top_level_is_admin(monkeypatch):
    """Auth handles top-level is_admin (legacy token format)."""

    async def fake_verify(token):
        return {
            "sub": "admin@example.com",
            "teams": [],
            "is_admin": True,  # Top-level is_admin (legacy format)
        }

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer good-token")])

    async def send(msg):
        pass

    result = await streamable_http_auth(scope, None, send)

    assert result is True

    user_ctx = tr.user_context_var.get()
    assert user_ctx.get("is_admin") is True  # Should recognize top-level is_admin


@pytest.mark.asyncio
async def test_streamable_http_auth_nested_is_admin_takes_precedence(monkeypatch):
    """Auth checks both top-level and nested is_admin."""

    async def fake_verify(token):
        return {
            "sub": "admin@example.com",
            "teams": [],
            "is_admin": False,  # Top-level says not admin
            "user": {"is_admin": True},  # Nested says admin
        }

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer good-token")])

    async def send(msg):
        pass

    result = await streamable_http_auth(scope, None, send)

    assert result is True

    user_ctx = tr.user_context_var.get()
    # Either top-level OR nested is_admin should grant admin access
    assert user_ctx.get("is_admin") is True


# ---------------------------------------------------------------------------
# Mixed Content Types and Metadata Preservation Tests (PR #2517 Regression)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_tool_with_image_content(monkeypatch):
    """Test call_tool correctly converts ImageContent with mimeType mapping and metadata."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, types

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_content = MagicMock()
    mock_content.type = "image"
    mock_content.data = "base64encodeddata"
    mock_content.mime_type = "image/png"
    mock_content.annotations = {"audience": ["user"]}
    mock_content.meta = {"source": "screenshot"}
    mock_result.content = [mock_content]
    mock_result.structured_content = None
    mock_result.model_dump = lambda by_alias=True: {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    result = await call_tool("image_tool", {})
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], types.ImageContent)
    assert result[0].type == "image"
    assert result[0].data == "base64encodeddata"
    assert result[0].mimeType == "image/png"  # Note: camelCase for MCP SDK
    # Annotations are converted to types.Annotations object
    assert result[0].annotations is not None
    assert result[0].annotations.audience == ["user"]


@pytest.mark.asyncio
async def test_call_tool_with_audio_content(monkeypatch):
    """Test call_tool correctly converts AudioContent with mimeType mapping and metadata."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, types

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_content = MagicMock()
    mock_content.type = "audio"
    mock_content.data = "base64audiodata"
    mock_content.mime_type = "audio/mp3"
    mock_content.annotations = {"priority": 1.0}
    mock_content.meta = {"duration": "30s"}
    mock_result.content = [mock_content]
    mock_result.structured_content = None
    mock_result.model_dump = lambda by_alias=True: {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    result = await call_tool("audio_tool", {})
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], types.AudioContent)
    assert result[0].type == "audio"
    assert result[0].data == "base64audiodata"
    assert result[0].mimeType == "audio/mp3"
    # Annotations are converted to types.Annotations object
    assert result[0].annotations is not None
    assert result[0].annotations.priority == 1.0


@pytest.mark.asyncio
async def test_call_tool_with_resource_link_content(monkeypatch):
    """Test call_tool correctly converts ResourceLink with all fields including size and metadata."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, types

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_content = MagicMock()
    mock_content.type = "resource_link"
    mock_content.uri = "file:///path/to/file.txt"
    mock_content.name = "file.txt"
    mock_content.description = "A text file"
    mock_content.mime_type = "text/plain"
    mock_content.size = 1024
    mock_content.meta = {"modified": "2025-01-01"}
    mock_result.content = [mock_content]
    mock_result.structured_content = None
    mock_result.model_dump = lambda by_alias=True: {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    result = await call_tool("resource_link_tool", {})
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], types.ResourceLink)
    assert result[0].type == "resource_link"
    assert str(result[0].uri) == "file:///path/to/file.txt"
    assert result[0].name == "file.txt"
    assert result[0].description == "A text file"
    assert result[0].mimeType == "text/plain"
    assert result[0].size == 1024  # Regression: size must be preserved


@pytest.mark.asyncio
async def test_call_tool_with_embedded_resource_content(monkeypatch):
    """Test call_tool correctly handles EmbeddedResource via model_validate."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, types

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_content = MagicMock()
    mock_content.type = "resource"
    mock_content.model_dump = lambda by_alias=True, mode="json": {
        "type": "resource",
        "resource": {
            "uri": "file:///embedded.txt",
            "text": "embedded content",
            "mimeType": "text/plain",
        },
    }
    mock_result.content = [mock_content]
    mock_result.structured_content = None
    mock_result.model_dump = lambda by_alias=True: {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    result = await call_tool("embedded_resource_tool", {})
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], types.EmbeddedResource)
    assert result[0].type == "resource"


@pytest.mark.asyncio
async def test_call_tool_with_mixed_content_types(monkeypatch):
    """Test call_tool correctly handles mixed content types in a single response."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, types

    mock_db = MagicMock()
    mock_result = MagicMock()

    # Create multiple content types
    text_content = MagicMock()
    text_content.type = "text"
    text_content.text = "Hello"
    text_content.annotations = None
    text_content.meta = None

    image_content = MagicMock()
    image_content.type = "image"
    image_content.data = "imgdata"
    image_content.mime_type = "image/jpeg"
    image_content.annotations = None
    image_content.meta = None

    resource_link_content = MagicMock()
    resource_link_content.type = "resource_link"
    resource_link_content.uri = "https://example.com/file"
    resource_link_content.name = "file"
    resource_link_content.description = None
    resource_link_content.mime_type = None
    resource_link_content.size = None
    resource_link_content.meta = None

    mock_result.content = [text_content, image_content, resource_link_content]
    mock_result.structured_content = None
    mock_result.model_dump = lambda by_alias=True: {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    result = await call_tool("mixed_tool", {})
    assert isinstance(result, list)
    assert len(result) == 3
    assert isinstance(result[0], types.TextContent)
    assert isinstance(result[1], types.ImageContent)
    assert isinstance(result[2], types.ResourceLink)


@pytest.mark.asyncio
async def test_call_tool_preserves_text_metadata(monkeypatch):
    """Test call_tool preserves annotations and _meta for TextContent."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, types

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_content = MagicMock()
    mock_content.type = "text"
    mock_content.text = "Content with metadata"
    mock_content.annotations = {"audience": ["assistant"], "priority": 0.8}
    mock_content.meta = {"generated_at": "2025-01-27T12:00:00Z"}
    mock_result.content = [mock_content]
    mock_result.structured_content = None
    mock_result.model_dump = lambda by_alias=True: {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    result = await call_tool("metadata_tool", {})
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], types.TextContent)
    assert result[0].text == "Content with metadata"
    # Regression: annotations must be preserved (converted to types.Annotations object)
    assert result[0].annotations is not None
    assert result[0].annotations.audience == ["assistant"]
    assert result[0].annotations.priority == 0.8


@pytest.mark.asyncio
async def test_call_tool_handles_unknown_content_type(monkeypatch):
    """Test call_tool gracefully handles unknown content types by converting to TextContent."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, types

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_content = MagicMock()
    mock_content.type = "unknown_future_type"
    mock_content.model_dump = lambda by_alias=True, mode="json": {"type": "unknown_future_type", "data": "something"}
    mock_result.content = [mock_content]
    mock_result.structured_content = None
    mock_result.model_dump = lambda by_alias=True: {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    result = await call_tool("unknown_type_tool", {})
    assert isinstance(result, list)
    assert len(result) == 1
    # Unknown types should be converted to TextContent with JSON representation
    assert isinstance(result[0], types.TextContent)
    assert result[0].type == "text"
    assert "unknown_future_type" in result[0].text


@pytest.mark.asyncio
async def test_call_tool_handles_missing_optional_metadata(monkeypatch):
    """Test call_tool handles content without optional metadata fields (annotations, meta, size)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, types

    mock_db = MagicMock()
    mock_result = MagicMock()

    # Content without optional attributes (simulating minimal response)
    mock_content = MagicMock(spec=["type", "text"])
    mock_content.type = "text"
    mock_content.text = "Minimal content"
    # Ensure getattr returns None for missing attributes
    del mock_content.annotations
    del mock_content.meta

    mock_result.content = [mock_content]
    mock_result.structured_content = None
    mock_result.model_dump = lambda by_alias=True: {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    result = await call_tool("minimal_tool", {})
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], types.TextContent)
    assert result[0].text == "Minimal content"
    # Should not raise even when annotations/meta are missing
    assert result[0].annotations is None


@pytest.mark.asyncio
async def test_call_tool_resource_link_preserves_all_fields(monkeypatch):
    """Regression test: ResourceLink must preserve all fields including size and _meta (Issue #2512)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, types

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_content = MagicMock()
    mock_content.type = "resource_link"
    mock_content.uri = "s3://bucket/large-file.bin"
    mock_content.name = "large-file.bin"
    mock_content.description = "A large binary file"
    mock_content.mime_type = "application/octet-stream"
    mock_content.size = 10485760  # 10 MB - critical field that was being dropped
    mock_content.meta = {"checksum": "sha256:abc123", "uploaded_by": "user@example.com"}
    mock_result.content = [mock_content]
    mock_result.structured_content = None
    mock_result.model_dump = lambda by_alias=True: {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    result = await call_tool("s3_link_tool", {})
    assert isinstance(result, list)
    assert len(result) == 1
    resource_link = result[0]
    assert isinstance(resource_link, types.ResourceLink)

    # Verify ALL fields are preserved (this was the bug fixed in PR #2517)
    assert str(resource_link.uri) == "s3://bucket/large-file.bin"
    assert resource_link.name == "large-file.bin"
    assert resource_link.description == "A large binary file"
    assert resource_link.mimeType == "application/octet-stream"
    assert resource_link.size == 10485760  # CRITICAL: size must not be dropped


@pytest.mark.asyncio
async def test_call_tool_with_gateway_model_annotations(monkeypatch):
    """Regression test: Gateway model Annotations must be converted to dict for MCP SDK compatibility.

    mcpgateway.common.models.Annotations is a different class from mcp.types.Annotations.
    Passing gateway Annotations directly to mcp.types.TextContent raises a ValidationError.
    This test uses the actual gateway model types to verify the conversion works.
    """
    # First-Party
    from mcpgateway.common.models import Annotations as GatewayAnnotations
    from mcpgateway.common.models import TextContent as GatewayTextContent
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, types

    mock_db = MagicMock()
    mock_result = MagicMock()

    # Create actual gateway model content with gateway Annotations (not a dict!)
    gateway_annotations = GatewayAnnotations(audience=["user"], priority=0.8)
    gateway_content = GatewayTextContent(
        type="text",
        text="Content with gateway annotations",
        annotations=gateway_annotations,
        meta={"source": "test"},
    )

    mock_result.content = [gateway_content]
    mock_result.structured_content = None
    mock_result.model_dump = lambda by_alias=True: {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    # This should NOT raise a ValidationError - the fix converts annotations to dict
    result = await call_tool("gateway_annotations_tool", {})

    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], types.TextContent)
    assert result[0].text == "Content with gateway annotations"

    # Verify annotations were converted and preserved
    assert result[0].annotations is not None
    assert isinstance(result[0].annotations, types.Annotations)  # MCP SDK type, not gateway type
    assert result[0].annotations.audience == ["user"]
    assert result[0].annotations.priority == 0.8


@pytest.mark.asyncio
async def test_call_tool_with_gateway_model_image_annotations(monkeypatch):
    """Regression test: Gateway ImageContent with Annotations must be converted correctly."""
    # First-Party
    from mcpgateway.common.models import Annotations as GatewayAnnotations
    from mcpgateway.common.models import ImageContent as GatewayImageContent
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, types

    mock_db = MagicMock()
    mock_result = MagicMock()

    # Create actual gateway model content with gateway Annotations
    gateway_annotations = GatewayAnnotations(audience=["assistant"], priority=0.5)
    gateway_content = GatewayImageContent(
        type="image",
        data="base64imagedata",
        mime_type="image/png",
        annotations=gateway_annotations,
    )

    mock_result.content = [gateway_content]
    mock_result.structured_content = None
    mock_result.model_dump = lambda by_alias=True: {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    # This should NOT raise a ValidationError
    result = await call_tool("gateway_image_tool", {})

    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], types.ImageContent)
    assert result[0].data == "base64imagedata"
    assert result[0].mimeType == "image/png"

    # Verify annotations were converted
    assert result[0].annotations is not None
    assert isinstance(result[0].annotations, types.Annotations)
    assert result[0].annotations.audience == ["assistant"]
    assert result[0].annotations.priority == 0.5


# ---------------------------------------------------------------------------
# InMemoryEventStore edge cases (Lines 370, 374, 381)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_store_replay_buffer_none_after_lookup():
    """replay_events_after returns None when event exists in index but stream buffer is gone."""
    store = InMemoryEventStore(max_events_per_stream=10)
    eid = await store.store_event("s1", {"id": 1})
    # Manually remove the stream buffer but keep the event in event_index
    del store.streams["s1"]
    sent = []

    async def collector(msg):
        sent.append(msg)

    result = await store.replay_events_after(eid, collector)
    assert result is None  # Line 370: buffer is None -> return None
    assert sent == []


@pytest.mark.asyncio
async def test_event_store_replay_seq_out_of_range():
    """replay_events_after returns None when event seq_num is outside buffer range."""
    store = InMemoryEventStore(max_events_per_stream=10)
    eid1 = await store.store_event("s1", {"id": 1})
    # Manually move start_seq past the event's seq_num to simulate out-of-range
    store.streams["s1"].start_seq = 100
    store.streams["s1"].next_seq = 101
    sent = []

    async def collector(msg):
        sent.append(msg)

    result = await store.replay_events_after(eid1, collector)
    assert result is None  # Line 374: seq_num < start_seq -> return None
    assert sent == []


@pytest.mark.asyncio
async def test_event_store_replay_skips_overwritten_slot():
    """replay_events_after skips slots where entry.seq_num != expected seq (line 381)."""
    store = InMemoryEventStore(max_events_per_stream=3)
    eid1 = await store.store_event("s1", {"id": 1})
    await store.store_event("s1", {"id": 2})
    # Manually corrupt the second slot so entry.seq_num != expected seq
    buffer = store.streams["s1"]
    idx = 1 % store.max_events_per_stream
    entry = buffer.entries[idx]
    if entry is not None:
        # Create a new entry with a different seq_num to simulate overwrite
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import EventEntry

        buffer.entries[idx] = EventEntry(
            event_id=entry.event_id,
            stream_id=entry.stream_id,
            message=entry.message,
            seq_num=999,  # Wrong seq_num
        )
    sent = []

    async def collector(msg):
        sent.append(msg)

    result = await store.replay_events_after(eid1, collector)
    assert result == "s1"
    assert sent == []  # Line 381: entry.seq_num != seq -> continue (skipped)


@pytest.mark.asyncio
async def test_event_store_replay_skips_none_entry():
    """replay_events_after skips slots where entry is None (line 380-381)."""
    store = InMemoryEventStore(max_events_per_stream=5)
    eid1 = await store.store_event("s1", {"id": 1})
    await store.store_event("s1", {"id": 2})
    # Manually set the second entry slot to None
    buffer = store.streams["s1"]
    idx = 1 % store.max_events_per_stream
    buffer.entries[idx] = None
    sent = []

    async def collector(msg):
        sent.append(msg)

    result = await store.replay_events_after(eid1, collector)
    assert result == "s1"
    assert sent == []  # None entry -> continue


# ---------------------------------------------------------------------------
# get_db error paths (Lines 422-443)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_db_cancelled_error():
    """get_db rolls back and closes session on CancelledError."""
    # Standard
    import asyncio

    with patch("mcpgateway.transports.streamablehttp_transport.SessionLocal") as mock_session_local:
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db

        # First-Party
        from mcpgateway.transports.streamablehttp_transport import get_db

        with pytest.raises(asyncio.CancelledError):
            async with get_db():
                raise asyncio.CancelledError()

        mock_db.rollback.assert_called_once()
        mock_db.close.assert_called()


@pytest.mark.asyncio
async def test_get_db_cancelled_error_rollback_fails():
    """get_db handles rollback failure during CancelledError."""
    # Standard
    import asyncio

    with patch("mcpgateway.transports.streamablehttp_transport.SessionLocal") as mock_session_local:
        mock_db = MagicMock()
        mock_db.rollback.side_effect = Exception("rollback fail")
        mock_session_local.return_value = mock_db

        # First-Party
        from mcpgateway.transports.streamablehttp_transport import get_db

        with pytest.raises(asyncio.CancelledError):
            async with get_db():
                raise asyncio.CancelledError()

        mock_db.close.assert_called()


@pytest.mark.asyncio
async def test_get_db_cancelled_error_close_fails():
    """get_db handles close failure during CancelledError."""
    # Standard
    import asyncio

    with patch("mcpgateway.transports.streamablehttp_transport.SessionLocal") as mock_session_local:
        mock_db = MagicMock()
        # close is called twice: once in the CancelledError handler (line 431), then in finally (line 445).
        # The first call (in the handler) should fail; the second (in finally) should succeed.
        mock_db.close.side_effect = [Exception("close fail"), None]
        mock_session_local.return_value = mock_db

        # First-Party
        from mcpgateway.transports.streamablehttp_transport import get_db

        with pytest.raises(asyncio.CancelledError):
            async with get_db():
                raise asyncio.CancelledError()


@pytest.mark.asyncio
async def test_get_db_exception_rollback_fails_then_invalidate():
    """get_db calls invalidate() when rollback fails on exception."""
    with patch("mcpgateway.transports.streamablehttp_transport.SessionLocal") as mock_session_local:
        mock_db = MagicMock()
        mock_db.rollback.side_effect = Exception("rollback fail")
        mock_session_local.return_value = mock_db

        # First-Party
        from mcpgateway.transports.streamablehttp_transport import get_db

        with pytest.raises(ValueError, match="test error"):
            async with get_db():
                raise ValueError("test error")

        mock_db.rollback.assert_called_once()
        mock_db.invalidate.assert_called_once()
        mock_db.close.assert_called()


@pytest.mark.asyncio
async def test_get_db_exception_rollback_and_invalidate_both_fail():
    """get_db handles both rollback and invalidate failing on exception."""
    with patch("mcpgateway.transports.streamablehttp_transport.SessionLocal") as mock_session_local:
        mock_db = MagicMock()
        mock_db.rollback.side_effect = Exception("rollback fail")
        mock_db.invalidate.side_effect = Exception("invalidate fail")
        mock_session_local.return_value = mock_db

        # First-Party
        from mcpgateway.transports.streamablehttp_transport import get_db

        with pytest.raises(ValueError, match="test error"):
            async with get_db():
                raise ValueError("test error")

        mock_db.rollback.assert_called_once()
        mock_db.invalidate.assert_called_once()
        mock_db.close.assert_called()


# ---------------------------------------------------------------------------
# get_user_email_from_context edge cases (Line 458)
# ---------------------------------------------------------------------------


def test_get_user_email_from_context_non_dict():
    """get_user_email_from_context returns str(user) for non-dict user context."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import get_user_email_from_context, user_context_var

    token = user_context_var.set("someuser@test.com")
    try:
        result = get_user_email_from_context()
        assert result == "someuser@test.com"  # Line 458: str(user)
    finally:
        user_context_var.reset(token)


def test_get_user_email_from_context_empty():
    """get_user_email_from_context returns 'unknown' for empty/falsy user context."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import get_user_email_from_context, user_context_var

    token = user_context_var.set("")
    try:
        result = get_user_email_from_context()
        assert result == "unknown"  # Line 458: not user -> "unknown"
    finally:
        user_context_var.reset(token)


def test_get_user_email_from_context_sub_fallback():
    """get_user_email_from_context uses sub when email is not present."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import get_user_email_from_context, user_context_var

    token = user_context_var.set({"sub": "sub@test.com"})
    try:
        result = get_user_email_from_context()
        assert result == "sub@test.com"  # Line 457: user.get("sub")
    finally:
        user_context_var.reset(token)


def test_get_user_email_from_context_no_email_no_sub():
    """get_user_email_from_context returns 'unknown' when dict has no email or sub."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import get_user_email_from_context, user_context_var

    token = user_context_var.set({"teams": []})
    try:
        result = get_user_email_from_context()
        assert result == "unknown"  # Line 457: "unknown" fallback
    finally:
        user_context_var.reset(token)


# ---------------------------------------------------------------------------
# call_tool: _meta extraction edge cases (Lines 518-519)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_tool_with_request_context_meta(monkeypatch):
    """Test call_tool extracts _meta from request context when available."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, mcp_app, tool_service

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_content = MagicMock()
    mock_content.type = "text"
    mock_content.text = "hello"
    mock_content.annotations = None
    mock_content.meta = None
    mock_result.content = [mock_content]
    mock_result.structured_content = None
    mock_result.model_dump = lambda by_alias=True: {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    # Mock request_context to have meta
    mock_ctx = MagicMock()
    mock_meta = MagicMock()
    mock_meta.model_dump.return_value = {"progressToken": "tok123"}
    mock_ctx.meta = mock_meta

    # Use a property mock for request_context
    type(mcp_app).request_context = property(lambda self: mock_ctx)
    try:
        result = await call_tool("mytool", {})
        assert isinstance(result, list)
        assert len(result) == 1
    finally:
        # Reset - use property that raises LookupError (original behavior)
        type(mcp_app).request_context = property(lambda self: (_ for _ in ()).throw(LookupError))


@pytest.mark.asyncio
async def test_call_tool_with_request_context_no_meta(monkeypatch):
    """Test call_tool tolerates an active request context that has no meta."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, mcp_app, tool_service, types

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_content = MagicMock()
    mock_content.type = "text"
    mock_content.text = "hello"
    mock_content.annotations = None
    mock_content.meta = None
    mock_result.content = [mock_content]
    mock_result.structured_content = None
    mock_result.model_dump = lambda by_alias=True: {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    mock_ctx = MagicMock()
    mock_ctx.meta = None

    type(mcp_app).request_context = property(lambda self: mock_ctx)
    try:
        result = await call_tool("mytool", {})
        assert isinstance(result, list)
        assert isinstance(result[0], types.TextContent)
    finally:
        type(mcp_app).request_context = property(lambda self: (_ for _ in ()).throw(LookupError))


# ---------------------------------------------------------------------------
# call_tool: admin bypass and team scoping in call_tool (Lines 532, 534-544)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_tool_admin_bypass(monkeypatch):
    """Test call_tool admin bypass sets user_email=None for unrestricted admin."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, user_context_var

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_content = MagicMock()
    mock_content.type = "text"
    mock_content.text = "admin result"
    mock_content.annotations = None
    mock_content.meta = None
    mock_result.content = [mock_content]
    mock_result.structured_content = None
    mock_result.model_dump = lambda by_alias=True: {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    captured_kwargs = {}

    async def mock_invoke(db, name, arguments, **kwargs):
        captured_kwargs.update(kwargs)
        return mock_result

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", mock_invoke)

    # Set admin context with teams=None (unrestricted)
    token = user_context_var.set({"email": "admin@test.com", "teams": None, "is_admin": True})
    try:
        result = await call_tool("mytool", {"arg": "val"})
        assert isinstance(result, list)
        # Admin bypass: user_email should be None
        assert captured_kwargs["user_email"] is None
        assert captured_kwargs["token_teams"] is None  # Unrestricted
    finally:
        user_context_var.reset(token)


@pytest.mark.asyncio
async def test_call_tool_non_admin_no_teams_gets_public_only(monkeypatch):
    """Test call_tool sets token_teams=[] for non-admin without teams (line 534-535)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, user_context_var

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_content = MagicMock()
    mock_content.type = "text"
    mock_content.text = "public result"
    mock_content.annotations = None
    mock_content.meta = None
    mock_result.content = [mock_content]
    mock_result.structured_content = None
    mock_result.model_dump = lambda by_alias=True: {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    captured_kwargs = {}

    async def mock_invoke(db, name, arguments, **kwargs):
        captured_kwargs.update(kwargs)
        return mock_result

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", mock_invoke)

    # Set non-admin context with teams=None
    token = user_context_var.set({"email": "user@test.com", "teams": None, "is_admin": False})
    try:
        result = await call_tool("mytool", {"arg": "val"})
        assert isinstance(result, list)
        # Non-admin without teams -> public-only
        assert captured_kwargs["token_teams"] == []
    finally:
        user_context_var.reset(token)


@pytest.mark.asyncio
async def test_call_tool_with_mcp_session_header(monkeypatch):
    """Test call_tool extracts mcp-session-id from request headers (lines 543-544)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, request_headers_var, tool_service, user_context_var

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_content = MagicMock()
    mock_content.type = "text"
    mock_content.text = "result"
    mock_content.annotations = None
    mock_content.meta = None
    mock_result.content = [mock_content]
    mock_result.structured_content = None
    mock_result.model_dump = lambda by_alias=True: {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))
    # Disable session affinity to avoid forwarding code
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", False)

    # Set request headers with mcp-session-id
    headers_token = request_headers_var.set({"mcp-session-id": "session-123", "Authorization": "Bearer tok"})
    user_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})
    try:
        result = await call_tool("mytool", {})
        assert isinstance(result, list)
    finally:
        request_headers_var.reset(headers_token)
        user_context_var.reset(user_token)


# ---------------------------------------------------------------------------
# list_tools: admin bypass branch (Lines 789, 791->794)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tools_admin_bypass(monkeypatch):
    """Test list_tools admin bypass with teams=None."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_tools, server_id_var, tool_service, user_context_var

    mock_db = MagicMock()
    mock_tool = MagicMock()
    mock_tool.name = "admin_tool"
    mock_tool.title = None
    mock_tool.description = "admin tool desc"
    mock_tool.input_schema = {"type": "object"}
    mock_tool.output_schema = None
    mock_tool.annotations = {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    captured_kwargs = {}

    async def mock_list_tools(db, include_inactive=False, limit=0, **kwargs):
        captured_kwargs.update(kwargs)
        return ([mock_tool], None)

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "list_tools", mock_list_tools)

    server_token = server_id_var.set(None)
    user_token = user_context_var.set({"email": "admin@test.com", "teams": None, "is_admin": True})
    try:
        result = await list_tools()
        assert len(result) == 1
        assert result[0].name == "admin_tool"
        # Admin bypass: user_email should be None, token_teams should be None
        assert captured_kwargs["user_email"] is None
        assert captured_kwargs["token_teams"] is None
    finally:
        server_id_var.reset(server_token)
        user_context_var.reset(user_token)


@pytest.mark.asyncio
async def test_list_tools_non_admin_no_teams(monkeypatch):
    """Test list_tools non-admin with teams=None gets public-only (line 791->794)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_tools, server_id_var, tool_service, user_context_var

    mock_db = MagicMock()
    mock_tool = MagicMock()
    mock_tool.name = "public_tool"
    mock_tool.title = None
    mock_tool.description = "public tool desc"
    mock_tool.input_schema = {"type": "object"}
    mock_tool.output_schema = None
    mock_tool.annotations = {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    captured_kwargs = {}

    async def mock_list_tools(db, include_inactive=False, limit=0, **kwargs):
        captured_kwargs.update(kwargs)
        return ([mock_tool], None)

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "list_tools", mock_list_tools)

    server_token = server_id_var.set(None)
    user_token = user_context_var.set({"email": "user@test.com", "teams": None, "is_admin": False})
    try:
        result = await list_tools()
        assert len(result) == 1
        # Non-admin: token_teams should be [] (public-only)
        assert captured_kwargs["token_teams"] == []
    finally:
        server_id_var.reset(server_token)
        user_context_var.reset(user_token)


# ---------------------------------------------------------------------------
# list_prompts: admin bypass branches (Lines 841, 843->846)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_prompts_admin_bypass(monkeypatch):
    """Test list_prompts admin bypass with teams=None."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_prompts, prompt_service, server_id_var, user_context_var

    mock_db = MagicMock()
    mock_prompt = MagicMock()
    mock_prompt.name = "admin_prompt"
    mock_prompt.title = None
    mock_prompt.description = "admin prompt desc"
    mock_prompt.arguments = []

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    captured_kwargs = {}

    async def mock_list_prompts(db, include_inactive=False, limit=0, **kwargs):
        captured_kwargs.update(kwargs)
        return ([mock_prompt], None)

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(prompt_service, "list_prompts", mock_list_prompts)

    server_token = server_id_var.set(None)
    user_token = user_context_var.set({"email": "admin@test.com", "teams": None, "is_admin": True})
    try:
        result = await list_prompts()
        assert len(result) == 1
        assert captured_kwargs["user_email"] is None
        assert captured_kwargs["token_teams"] is None
    finally:
        server_id_var.reset(server_token)
        user_context_var.reset(user_token)


# ---------------------------------------------------------------------------
# get_prompt: admin bypass and _meta extraction (Lines 897, 899->902, 906-907)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_prompt_admin_bypass(monkeypatch):
    """Test get_prompt admin bypass with teams=None (line 897)."""
    # Third-Party
    from mcp.types import PromptMessage, TextContent

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import get_prompt, prompt_service, types, user_context_var

    mock_db = MagicMock()
    mock_message = PromptMessage(role="user", content=TextContent(type="text", text="admin prompt"))
    mock_result = MagicMock()
    mock_result.messages = [mock_message]
    mock_result.description = "admin prompt desc"

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    captured_kwargs = {}

    async def mock_get_prompt(db, prompt_id, arguments=None, **kwargs):
        captured_kwargs.update(kwargs)
        return mock_result

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(prompt_service, "get_prompt", mock_get_prompt)

    user_token = user_context_var.set({"email": "admin@test.com", "teams": None, "is_admin": True})
    try:
        result = await get_prompt("test_prompt", {"arg1": "val1"})
        assert isinstance(result, types.GetPromptResult)
        assert captured_kwargs["user"] is None  # Admin bypass
        assert captured_kwargs["token_teams"] is None
    finally:
        user_context_var.reset(user_token)


@pytest.mark.asyncio
async def test_get_prompt_non_admin_no_teams(monkeypatch):
    """Test get_prompt non-admin with teams=None gets public-only (line 899->902)."""
    # Third-Party
    from mcp.types import PromptMessage, TextContent

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import get_prompt, prompt_service, types, user_context_var

    mock_db = MagicMock()
    mock_message = PromptMessage(role="user", content=TextContent(type="text", text="public"))
    mock_result = MagicMock()
    mock_result.messages = [mock_message]
    mock_result.description = "desc"

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    captured_kwargs = {}

    async def mock_get_prompt(db, prompt_id, arguments=None, **kwargs):
        captured_kwargs.update(kwargs)
        return mock_result

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(prompt_service, "get_prompt", mock_get_prompt)

    user_token = user_context_var.set({"email": "user@test.com", "teams": None, "is_admin": False})
    try:
        result = await get_prompt("test_prompt")
        assert isinstance(result, types.GetPromptResult)
        assert captured_kwargs["token_teams"] == []  # public-only
    finally:
        user_context_var.reset(user_token)


# ---------------------------------------------------------------------------
# list_resources: admin bypass (Lines 966, 968->971)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_resources_admin_bypass(monkeypatch):
    """Test list_resources admin bypass with teams=None (line 966)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_resources, resource_service, server_id_var, user_context_var

    mock_db = MagicMock()
    mock_resource = MagicMock()
    mock_resource.uri = "file:///admin.txt"
    mock_resource.name = "admin resource"
    mock_resource.title = None
    mock_resource.description = "admin desc"
    mock_resource.mime_type = "text/plain"

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    captured_kwargs = {}

    async def mock_list_resources(db, include_inactive=False, limit=0, **kwargs):
        captured_kwargs.update(kwargs)
        return ([mock_resource], None)

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(resource_service, "list_resources", mock_list_resources)

    server_token = server_id_var.set(None)
    user_token = user_context_var.set({"email": "admin@test.com", "teams": None, "is_admin": True})
    try:
        result = await list_resources()
        assert len(result) == 1
        assert captured_kwargs["user_email"] is None
        assert captured_kwargs["token_teams"] is None
    finally:
        server_id_var.reset(server_token)
        user_context_var.reset(user_token)


# ---------------------------------------------------------------------------
# read_resource: admin bypass and blob return (Lines 1021, 1023->1026, 1030-1031, 1053)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_resource_admin_bypass(monkeypatch):
    """Test read_resource admin bypass with teams=None (line 1021)."""
    # Third-Party
    from pydantic import AnyUrl

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import read_resource, resource_service, user_context_var

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_result.text = "admin resource content"
    mock_result.blob = None

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    captured_kwargs = {}

    async def mock_read_resource(db, resource_uri, **kwargs):
        captured_kwargs.update(kwargs)
        return mock_result

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(resource_service, "read_resource", mock_read_resource)

    user_token = user_context_var.set({"email": "admin@test.com", "teams": None, "is_admin": True})
    try:
        test_uri = AnyUrl("file:///admin.txt")
        result = await read_resource(test_uri)
        assert result == "admin resource content"
        assert captured_kwargs["user"] is None
        assert captured_kwargs["token_teams"] is None
    finally:
        user_context_var.reset(user_token)


@pytest.mark.asyncio
async def test_read_resource_returns_blob(monkeypatch):
    """Test read_resource returns blob content when available (line 1053)."""
    # Third-Party
    from pydantic import AnyUrl

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import read_resource, resource_service

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_result.blob = b"binary content here"
    mock_result.text = None

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(resource_service, "read_resource", AsyncMock(return_value=mock_result))

    test_uri = AnyUrl("file:///binary.bin")
    result = await read_resource(test_uri)
    assert result == b"binary content here"


# ---------------------------------------------------------------------------
# list_resource_templates error paths (Lines 1106-1111)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_resource_templates_inner_exception(monkeypatch):
    """Test list_resource_templates returns [] on inner service exception (line 1106-1108)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_resource_templates, resource_service, user_context_var

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(resource_service, "list_resource_templates", AsyncMock(side_effect=Exception("inner fail")))

    user_token = user_context_var.set({"email": "user@test.com", "teams": [], "is_admin": False})
    try:
        result = await list_resource_templates()
        assert result == []
    finally:
        user_context_var.reset(user_token)


@pytest.mark.asyncio
async def test_list_resource_templates_outer_exception(monkeypatch, caplog):
    """Test list_resource_templates returns [] on outer exception (line 1109-1111)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_resource_templates, user_context_var

    @asynccontextmanager
    async def failing_get_db():
        raise Exception("db fail!")
        yield  # pragma: no cover

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", failing_get_db)

    user_token = user_context_var.set({"email": "user@test.com", "teams": [], "is_admin": False})
    try:
        with caplog.at_level("ERROR"):
            result = await list_resource_templates()
            assert result == []
            assert "Error listing resource templates" in caplog.text
    finally:
        user_context_var.reset(user_token)


# ---------------------------------------------------------------------------
# set_logging_level (Lines 1131-1148)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_logging_level_debug():
    """Test set_logging_level with debug level."""
    # Third-Party
    from mcp import types as mcp_types

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import set_logging_level

    with patch("mcpgateway.transports.streamablehttp_transport.logging_service") as mock_ls:
        mock_ls.set_level = AsyncMock()
        result = await set_logging_level("debug")
        assert isinstance(result, mcp_types.EmptyResult)
        mock_ls.set_level.assert_called_once()


@pytest.mark.asyncio
async def test_set_logging_level_warning():
    """Test set_logging_level with warning level."""
    # Third-Party
    from mcp import types as mcp_types

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import set_logging_level

    with patch("mcpgateway.transports.streamablehttp_transport.logging_service") as mock_ls:
        mock_ls.set_level = AsyncMock()
        result = await set_logging_level("warning")
        assert isinstance(result, mcp_types.EmptyResult)
        mock_ls.set_level.assert_called_once()


@pytest.mark.asyncio
async def test_set_logging_level_error():
    """Test set_logging_level with error level."""
    # Third-Party
    from mcp import types as mcp_types

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import set_logging_level

    with patch("mcpgateway.transports.streamablehttp_transport.logging_service") as mock_ls:
        mock_ls.set_level = AsyncMock()
        result = await set_logging_level("error")
        assert isinstance(result, mcp_types.EmptyResult)


@pytest.mark.asyncio
async def test_set_logging_level_critical():
    """Test set_logging_level with critical level."""
    # Third-Party
    from mcp import types as mcp_types

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import set_logging_level

    with patch("mcpgateway.transports.streamablehttp_transport.logging_service") as mock_ls:
        mock_ls.set_level = AsyncMock()
        result = await set_logging_level("critical")
        assert isinstance(result, mcp_types.EmptyResult)


@pytest.mark.asyncio
async def test_set_logging_level_notice():
    """Test set_logging_level with notice maps to INFO."""
    # Third-Party
    from mcp import types as mcp_types

    # First-Party
    from mcpgateway.common.models import LogLevel
    from mcpgateway.transports.streamablehttp_transport import set_logging_level

    with patch("mcpgateway.transports.streamablehttp_transport.logging_service") as mock_ls:
        mock_ls.set_level = AsyncMock()
        result = await set_logging_level("notice")
        assert isinstance(result, mcp_types.EmptyResult)
        mock_ls.set_level.assert_called_once_with(LogLevel.INFO)


@pytest.mark.asyncio
async def test_set_logging_level_unknown_defaults_to_info():
    """Test set_logging_level with unknown level defaults to INFO."""
    # Third-Party
    from mcp import types as mcp_types

    # First-Party
    from mcpgateway.common.models import LogLevel
    from mcpgateway.transports.streamablehttp_transport import set_logging_level

    with patch("mcpgateway.transports.streamablehttp_transport.logging_service") as mock_ls:
        mock_ls.set_level = AsyncMock()
        result = await set_logging_level("unknown_level")
        assert isinstance(result, mcp_types.EmptyResult)
        mock_ls.set_level.assert_called_once_with(LogLevel.INFO)


@pytest.mark.asyncio
async def test_set_logging_level_exception():
    """Test set_logging_level returns EmptyResult on exception."""
    # Third-Party
    from mcp import types as mcp_types

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import set_logging_level

    with patch("mcpgateway.transports.streamablehttp_transport.logging_service") as mock_ls:
        mock_ls.set_level = AsyncMock(side_effect=Exception("level error"))
        result = await set_logging_level("info")
        assert isinstance(result, mcp_types.EmptyResult)


@pytest.mark.asyncio
async def test_set_logging_level_requires_servers_use(monkeypatch):
    """logging/setLevel requires admin.system_config permission for authenticated users."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import set_logging_level

    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default",
        AsyncMock(
            return_value=(
                "server-1",
                {},
                {"email": "dev@example.com", "teams": [], "is_admin": False, "is_authenticated": True},
            )
        ),
    )
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._check_server_oauth_enforcement", AsyncMock())
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._check_streamable_permission",
        AsyncMock(return_value=False),
    )

    mock_logging_service = MagicMock()
    mock_logging_service.set_level = AsyncMock()
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.logging_service", mock_logging_service)

    # Should raise PermissionError for non-admin user without admin.system_config
    with pytest.raises(PermissionError, match="Access denied"):
        await set_logging_level("info")
    mock_logging_service.set_level.assert_not_called()


@pytest.mark.asyncio
async def test_set_logging_level_admin_allowed(monkeypatch):
    """logging/setLevel succeeds when the caller has admin.system_config permission."""
    # Third-Party
    from mcp import types as mcp_types

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import set_logging_level

    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default",
        AsyncMock(
            return_value=(
                "server-1",
                {},
                {"email": "admin@example.com", "teams": None, "is_admin": True, "is_authenticated": True},
            )
        ),
    )
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._check_server_oauth_enforcement", AsyncMock())
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._check_streamable_permission",
        AsyncMock(return_value=True),
    )

    mock_logging_service = MagicMock()
    mock_logging_service.set_level = AsyncMock()
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.logging_service", mock_logging_service)

    result = await set_logging_level("info")
    assert isinstance(result, mcp_types.EmptyResult)
    mock_logging_service.set_level.assert_called_once()


# ---------------------------------------------------------------------------
# complete function (Lines 1177-1221)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_dict_result(monkeypatch):
    """Test complete returns Completion from dict result (line 1188-1190)."""
    # Third-Party
    from mcp import types as mcp_types

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import complete

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    mock_result = {"completion": {"values": ["val1", "val2"], "total": 2, "hasMore": False}}
    with patch("mcpgateway.transports.streamablehttp_transport.completion_service") as mock_cs:
        mock_cs.handle_completion = AsyncMock(return_value=mock_result)

        ref = mcp_types.PromptReference(type="ref/prompt", name="test")
        argument = MagicMock()
        argument.model_dump.return_value = {"name": "arg", "value": "v"}

        result = await complete(ref, argument)
        assert isinstance(result, mcp_types.Completion)
        assert result.values == ["val1", "val2"]


@pytest.mark.asyncio
async def test_complete_defaults_non_admin_without_teams_to_public_only_scope(monkeypatch):
    """Completion should use public-only scope when non-admin context has teams=None."""
    # Third-Party
    from mcp import types as mcp_types

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import complete

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default",
        AsyncMock(return_value=("server-1", {}, {"email": "viewer@example.com", "teams": None, "is_admin": False, "is_authenticated": True})),
    )

    mock_result = {"completion": {"values": ["public"], "total": 1, "hasMore": False}}
    with patch("mcpgateway.transports.streamablehttp_transport.completion_service") as mock_cs:
        mock_cs.handle_completion = AsyncMock(return_value=mock_result)

        ref = mcp_types.PromptReference(type="ref/prompt", name="test")
        argument = MagicMock()
        argument.model_dump.return_value = {"name": "arg", "value": "v"}

        result = await complete(ref, argument)
        assert isinstance(result, mcp_types.Completion)
        assert result.values == ["public"]
        assert mock_cs.handle_completion.await_args.kwargs["user_email"] == "viewer@example.com"
        assert mock_cs.handle_completion.await_args.kwargs["token_teams"] == []


@pytest.mark.asyncio
async def test_complete_preserves_admin_bypass_for_null_teams_context(monkeypatch):
    """Admin completion with explicit teams=None keeps unrestricted bypass semantics."""
    # Third-Party
    from mcp import types as mcp_types

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import complete

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default",
        AsyncMock(return_value=("server-1", {}, {"email": "admin@example.com", "teams": None, "is_admin": True, "is_authenticated": True})),
    )

    mock_result = {"completion": {"values": ["all"], "total": 1, "hasMore": False}}
    with patch("mcpgateway.transports.streamablehttp_transport.completion_service") as mock_cs:
        mock_cs.handle_completion = AsyncMock(return_value=mock_result)

        ref = mcp_types.PromptReference(type="ref/prompt", name="test")
        argument = MagicMock()
        argument.model_dump.return_value = {"name": "arg", "value": "v"}

        result = await complete(ref, argument)
        assert isinstance(result, mcp_types.Completion)
        assert result.values == ["all"]
        assert mock_cs.handle_completion.await_args.kwargs["user_email"] is None
        assert mock_cs.handle_completion.await_args.kwargs["token_teams"] is None


@pytest.mark.asyncio
async def test_complete_preserves_explicit_team_scope(monkeypatch):
    """Completion should preserve explicit token team scope from user context."""
    # Third-Party
    from mcp import types as mcp_types

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import complete

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default",
        AsyncMock(return_value=("server-1", {}, {"email": "member@example.com", "teams": ["team-1"], "is_admin": False, "is_authenticated": True})),
    )

    mock_result = {"completion": {"values": ["team"], "total": 1, "hasMore": False}}
    with patch("mcpgateway.transports.streamablehttp_transport.completion_service") as mock_cs:
        mock_cs.handle_completion = AsyncMock(return_value=mock_result)

        ref = mcp_types.PromptReference(type="ref/prompt", name="test")
        argument = MagicMock()
        argument.model_dump.return_value = {"name": "arg", "value": "v"}

        result = await complete(ref, argument)
        assert isinstance(result, mcp_types.Completion)
        assert result.values == ["team"]
        assert mock_cs.handle_completion.await_args.kwargs["user_email"] == "member@example.com"
        assert mock_cs.handle_completion.await_args.kwargs["token_teams"] == ["team-1"]


@pytest.mark.asyncio
async def test_complete_nested_completion(monkeypatch):
    """Test complete handles nested completion result (line 1200-1202)."""
    # Third-Party
    from mcp import types as mcp_types

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import complete

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    # Create a deeply nested result: result.completion.completion
    inner_completion = mcp_types.Completion(values=["nested_val"], total=1, hasMore=False)
    mid_result = MagicMock()
    mid_result.completion = inner_completion
    outer_result = MagicMock()
    outer_result.completion = mid_result

    with patch("mcpgateway.transports.streamablehttp_transport.completion_service") as mock_cs:
        mock_cs.handle_completion = AsyncMock(return_value=outer_result)

        ref = mcp_types.PromptReference(type="ref/prompt", name="test")
        argument = MagicMock()
        argument.model_dump.return_value = {"name": "arg", "value": "v"}

        result = await complete(ref, argument)
        assert isinstance(result, mcp_types.Completion)


@pytest.mark.asyncio
async def test_complete_completion_is_dict(monkeypatch):
    """Test complete handles when result.completion is a dict (line 1196-1197)."""
    # Third-Party
    from mcp import types as mcp_types

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import complete

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    outer_result = MagicMock()
    outer_result.completion = {"values": ["dict_val"], "total": 1, "hasMore": False}

    with patch("mcpgateway.transports.streamablehttp_transport.completion_service") as mock_cs:
        mock_cs.handle_completion = AsyncMock(return_value=outer_result)

        ref = mcp_types.PromptReference(type="ref/prompt", name="test")
        argument = MagicMock()
        argument.model_dump.return_value = {"name": "arg", "value": "v"}

        result = await complete(ref, argument)
        assert isinstance(result, mcp_types.Completion)
        assert result.values == ["dict_val"]


@pytest.mark.asyncio
async def test_complete_already_completion_type(monkeypatch):
    """Test complete returns result directly when it is already types.Completion (line 1213-1214)."""
    # Third-Party
    from mcp import types as mcp_types

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import complete

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    direct_result = mcp_types.Completion(values=["direct"], total=1, hasMore=False)

    with patch("mcpgateway.transports.streamablehttp_transport.completion_service") as mock_cs:
        mock_cs.handle_completion = AsyncMock(return_value=direct_result)

        ref = mcp_types.PromptReference(type="ref/prompt", name="test")
        argument = MagicMock()
        argument.model_dump.return_value = {"name": "arg", "value": "v"}

        result = await complete(ref, argument)
        assert isinstance(result, mcp_types.Completion)
        assert result.values == ["direct"]


@pytest.mark.asyncio
async def test_complete_completion_obj_is_completion_type(monkeypatch):
    """Test complete handles result.completion being types.Completion (line 1205-1206)."""
    # Third-Party
    from mcp import types as mcp_types

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import complete

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    completion_obj = mcp_types.Completion(values=["comp_val"], total=1, hasMore=False)
    outer_result = MagicMock()
    outer_result.completion = completion_obj
    # Make sure isinstance checks work - MagicMock won't pass isinstance(result, types.Completion)
    # so result must not be Completion type itself

    with patch("mcpgateway.transports.streamablehttp_transport.completion_service") as mock_cs:
        mock_cs.handle_completion = AsyncMock(return_value=outer_result)

        ref = mcp_types.PromptReference(type="ref/prompt", name="test")
        argument = MagicMock()
        argument.model_dump.return_value = {"name": "arg", "value": "v"}

        result = await complete(ref, argument)
        assert isinstance(result, mcp_types.Completion)
        assert result.values == ["comp_val"]


@pytest.mark.asyncio
async def test_complete_pydantic_model_completion(monkeypatch):
    """Test complete handles result.completion being a Pydantic model with model_dump (line 1209-1210)."""
    # Third-Party
    from mcp import types as mcp_types

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import complete

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    # Create a mock completion object that has model_dump but is not types.Completion
    mock_completion = MagicMock()
    mock_completion.model_dump.return_value = {"values": ["pydantic_val"], "total": 1, "hasMore": False}
    # Ensure isinstance checks fail for dict and types.Completion
    mock_completion.__class__ = type("CustomCompletion", (), {})
    # Must not have .completion attribute to not trigger nested check
    del mock_completion.completion

    outer_result = MagicMock()
    outer_result.completion = mock_completion

    with patch("mcpgateway.transports.streamablehttp_transport.completion_service") as mock_cs:
        mock_cs.handle_completion = AsyncMock(return_value=outer_result)

        ref = mcp_types.PromptReference(type="ref/prompt", name="test")
        argument = MagicMock()
        argument.model_dump.return_value = {"name": "arg", "value": "v"}

        result = await complete(ref, argument)
        assert isinstance(result, mcp_types.Completion)
        assert result.values == ["pydantic_val"]


@pytest.mark.asyncio
async def test_complete_completion_obj_without_model_dump_falls_back(monkeypatch):
    """Test complete falls back to empty Completion when result.completion is an unhandled type (line 1209->1213)."""
    # Third-Party
    from mcp import types as mcp_types

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import complete

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    outer_result = MagicMock()
    outer_result.completion = "weird"  # not dict, not Completion, no model_dump

    with patch("mcpgateway.transports.streamablehttp_transport.completion_service") as mock_cs:
        mock_cs.handle_completion = AsyncMock(return_value=outer_result)

        ref = mcp_types.PromptReference(type="ref/prompt", name="test")
        argument = MagicMock()
        argument.model_dump.return_value = {"name": "arg", "value": "v"}

        result = await complete(ref, argument)
        assert isinstance(result, mcp_types.Completion)
        assert result.values == []
        assert result.total == 0


@pytest.mark.asyncio
async def test_complete_fallback_empty(monkeypatch):
    """Test complete returns empty Completion on unhandled result type (line 1217)."""
    # Third-Party
    from mcp import types as mcp_types

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import complete

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    # Return something that doesn't match any known pattern
    weird_result = 42  # integer - no .completion, not dict, not Completion

    with patch("mcpgateway.transports.streamablehttp_transport.completion_service") as mock_cs:
        mock_cs.handle_completion = AsyncMock(return_value=weird_result)

        ref = mcp_types.PromptReference(type="ref/prompt", name="test")
        argument = MagicMock()
        argument.model_dump.return_value = {"name": "arg", "value": "v"}

        result = await complete(ref, argument)
        assert isinstance(result, mcp_types.Completion)
        assert result.values == []
        assert result.total == 0


@pytest.mark.asyncio
async def test_complete_exception(monkeypatch):
    """Test complete returns empty Completion on exception (line 1219-1221)."""
    # Third-Party
    from mcp import types as mcp_types

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import complete

    @asynccontextmanager
    async def failing_get_db():
        raise Exception("db fail!")
        yield  # pragma: no cover

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", failing_get_db)

    ref = mcp_types.PromptReference(type="ref/prompt", name="test")
    argument = MagicMock()
    argument.model_dump.return_value = {"name": "arg", "value": "v"}

    result = await complete(ref, argument)
    assert isinstance(result, mcp_types.Completion)
    assert result.values == []
    assert result.total == 0


# ---------------------------------------------------------------------------
# _get_oauth_experimental_config (Lines 1740-1750)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streamable_http_auth_proxy_user_when_client_auth_disabled(monkeypatch):
    """Test auth sets user context for proxy user when client auth disabled (lines 1740-1750)."""
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_client_auth_enabled", False)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.trust_proxy_auth", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.trust_proxy_auth_dangerously", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.proxy_user_header", "x-forwarded-user")

    scope = _make_scope(
        "/servers/1/mcp",
        headers=[
            (b"x-forwarded-user", b"proxy_user@example.com"),
        ],
    )
    sent = []

    async def send(msg):
        sent.append(msg)

    result = await streamable_http_auth(scope, None, send)
    assert result is True
    assert sent == []  # No 401 sent

    user_ctx = tr.user_context_var.get()
    assert user_ctx["email"] == "proxy_user@example.com"
    assert user_ctx["teams"] == []
    assert user_ctx["is_authenticated"] is True
    assert user_ctx["is_admin"] is False


# ---------------------------------------------------------------------------
# streamable_http_auth: proxy trust takes precedence over Bearer header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streamable_http_auth_proxy_user_with_bearer_header(monkeypatch):
    """Proxy auth takes precedence over Bearer when proxy trust is active; JWT is never attempted."""
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_client_auth_enabled", False)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.trust_proxy_auth", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.trust_proxy_auth_dangerously", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.proxy_user_header", "x-forwarded-user")

    scope = _make_scope(
        "/servers/1/mcp",
        headers=[
            (b"authorization", b"Bearer bad-token"),
            (b"x-forwarded-user", b"proxy_fallback@example.com"),
        ],
    )
    sent = []

    async def send(msg):
        sent.append(msg)

    result = await streamable_http_auth(scope, None, send)
    assert result is True
    assert sent == []

    user_ctx = tr.user_context_var.get()
    assert user_ctx["email"] == "proxy_fallback@example.com"
    assert user_ctx["teams"] == []
    assert user_ctx["is_admin"] is False


@pytest.mark.asyncio
async def test_streamable_http_auth_proxy_user_context_on_valid_jwt(monkeypatch):
    """Proxy auth takes precedence even when a valid JWT Bearer header is present."""

    async def fake_verify(token):
        # Return something that is truthy but not a dict
        return "string_payload"

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_client_auth_enabled", False)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.trust_proxy_auth", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.trust_proxy_auth_dangerously", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.proxy_user_header", "x-forwarded-user")

    scope = _make_scope(
        "/servers/1/mcp",
        headers=[
            (b"authorization", b"Bearer valid-token"),
            (b"x-forwarded-user", b"proxy_user@example.com"),
        ],
    )
    sent = []

    async def send(msg):
        sent.append(msg)

    result = await streamable_http_auth(scope, None, send)
    assert result is True

    user_ctx = tr.user_context_var.get()
    assert user_ctx["email"] == "proxy_user@example.com"


# ---------------------------------------------------------------------------
# streamable_http_auth: positive team membership cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streamable_http_auth_caches_positive_team_membership(monkeypatch):
    """Test auth caches positive team membership after DB check (line 1844)."""
    # Standard
    from unittest.mock import MagicMock, patch

    async def fake_verify(token):
        return {
            "sub": "valid_user@example.com",
            "teams": ["team_a"],
        }

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    # Mock auth_cache to return None (cache miss) so we go to DB
    mock_auth_cache = MagicMock()
    mock_auth_cache.get_team_membership_valid_sync.return_value = None
    mock_auth_cache.set_team_membership_valid_sync = MagicMock()

    # Mock DB to return the same teams (user IS a member)
    mock_db = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = ["team_a"]  # User IS a member of team_a
    mock_execute = MagicMock()
    mock_execute.scalars.return_value = mock_scalars
    mock_db.execute.return_value = mock_execute

    mock_session_local = MagicMock()
    mock_session_local.return_value.__enter__ = MagicMock(return_value=mock_db)
    mock_session_local.return_value.__exit__ = MagicMock(return_value=False)

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer token")])
    sent = []

    async def send(msg):
        sent.append(msg)

    with (
        patch("mcpgateway.cache.auth_cache.get_auth_cache", return_value=mock_auth_cache),
        patch("mcpgateway.transports.streamablehttp_transport.SessionLocal", mock_session_local),
    ):
        result = await streamable_http_auth(scope, None, send)

    assert result is True
    assert sent == []

    # Should have cached the positive result (line 1844)
    mock_auth_cache.set_team_membership_valid_sync.assert_called_once_with("valid_user@example.com", ["team_a"], True)


# ---------------------------------------------------------------------------
# streamable_http_auth: rollback exception in finally (Lines 1850-1851)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streamable_http_auth_db_context_manager(monkeypatch):
    """Test auth uses SQLAlchemy context manager for DB lifecycle."""
    # Standard
    from unittest.mock import MagicMock, patch

    async def fake_verify(token):
        return {
            "sub": "user@example.com",
            "teams": ["team_a"],
        }

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    mock_auth_cache = MagicMock()
    mock_auth_cache.get_team_membership_valid_sync.return_value = None
    mock_auth_cache.set_team_membership_valid_sync = MagicMock()

    mock_db = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = ["team_a"]
    mock_execute = MagicMock()
    mock_execute.scalars.return_value = mock_scalars
    mock_db.execute.return_value = mock_execute

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer token")])
    sent = []

    async def send(msg):
        sent.append(msg)

    mock_session_local = MagicMock()
    mock_session_local.return_value.__enter__ = MagicMock(return_value=mock_db)
    mock_session_local.return_value.__exit__ = MagicMock(return_value=False)

    with (
        patch("mcpgateway.cache.auth_cache.get_auth_cache", return_value=mock_auth_cache),
        patch("mcpgateway.transports.streamablehttp_transport.SessionLocal", mock_session_local),
    ):
        result = await streamable_http_auth(scope, None, send)

    assert result is True
    assert sent == []
    # Context manager handles close
    mock_session_local.return_value.__exit__.assert_called_once()


# ---------------------------------------------------------------------------
# call_tool: structured content from model_dump fallback (Lines 737-738, 744-745)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_tool_structured_content_getattr_exception(monkeypatch):
    """Test call_tool handles getattr exception for structured_content (lines 737-738)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service

    mock_db = MagicMock()

    # Use a custom class where structured_content property raises a non-AttributeError
    class BadResult:
        def __init__(self):
            self.content = []

        @property
        def structured_content(self):
            raise RuntimeError("getattr fails")

        def model_dump(self, by_alias=True):
            return {}

    mock_content = MagicMock()
    mock_content.type = "text"
    mock_content.text = "hello"
    mock_content.annotations = None
    mock_content.meta = None

    bad_result = BadResult()
    bad_result.content = [mock_content]

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=bad_result))

    result = await call_tool("mytool", {})
    assert isinstance(result, list)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_call_tool_structured_content_model_dump_exception(monkeypatch):
    """Test call_tool handles model_dump exception for structuredContent (lines 744-745)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_content = MagicMock()
    mock_content.type = "text"
    mock_content.text = "hello"
    mock_content.annotations = None
    mock_content.meta = None
    mock_result.content = [mock_content]
    mock_result.structured_content = None  # First check returns None
    mock_result.model_dump = MagicMock(side_effect=Exception("dump fail"))

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    result = await call_tool("mytool", {})
    assert isinstance(result, list)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# call_tool: _convert_meta with model_dump (Lines 675-677)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_tool_meta_with_model_dump(monkeypatch):
    """Test call_tool converts meta with model_dump (lines 675-677)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_content = MagicMock()
    mock_content.type = "text"
    mock_content.text = "hello"
    mock_content.annotations = None
    # Create a meta object with model_dump (like a Pydantic model)
    mock_meta = MagicMock()
    mock_meta.model_dump = MagicMock(return_value={"key": "value"})
    # Make isinstance(mock_meta, dict) return False
    mock_content.meta = mock_meta
    mock_result.content = [mock_content]
    mock_result.structured_content = None
    mock_result.model_dump = lambda by_alias=True: {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    result = await call_tool("mytool", {})
    assert isinstance(result, list)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# call_tool: annotations not convertible (Line 660)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_tool_annotations_not_convertible(monkeypatch):
    """Test call_tool handles annotations that are not dict, None, or model_dump (line 660)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_content = MagicMock()
    mock_content.type = "text"
    mock_content.text = "hello"
    # An annotation object that is not dict, not None, has no model_dump
    ann = MagicMock(spec=[])  # Empty spec, no model_dump
    mock_content.annotations = ann
    mock_content.meta = None
    mock_result.content = [mock_content]
    mock_result.structured_content = None
    mock_result.model_dump = lambda by_alias=True: {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    result = await call_tool("mytool", {})
    assert isinstance(result, list)
    assert len(result) == 1
    # annotations should be None since the object couldn't be converted
    assert result[0].annotations is None


# ---------------------------------------------------------------------------
# read_resource: _meta extraction (Lines 1030-1031)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_resource_non_admin_no_teams(monkeypatch):
    """Test read_resource non-admin with teams=None gets public-only (line 1023)."""
    # Third-Party
    from pydantic import AnyUrl

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import read_resource, resource_service, user_context_var

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_result.text = "public content"
    mock_result.blob = None

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    captured_kwargs = {}

    async def mock_read_resource(db, resource_uri, **kwargs):
        captured_kwargs.update(kwargs)
        return mock_result

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(resource_service, "read_resource", mock_read_resource)

    user_token = user_context_var.set({"email": "user@test.com", "teams": None, "is_admin": False})
    try:
        test_uri = AnyUrl("file:///public.txt")
        result = await read_resource(test_uri)
        assert result == "public content"
        assert captured_kwargs["token_teams"] == []  # public-only
    finally:
        user_context_var.reset(user_token)


# ---------------------------------------------------------------------------
# Proxy auth: no proxy user with client auth disabled (Line 1740->1753)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streamable_http_auth_no_proxy_user_when_client_auth_disabled(monkeypatch):
    """Test auth continues to JWT flow when client auth disabled but no proxy user header (line 1740->1753)."""
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_client_auth_enabled", False)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.trust_proxy_auth", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.trust_proxy_auth_dangerously", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.proxy_user_header", "x-forwarded-user")
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", False)
    # Stub out per-server OAuth check — this test validates proxy-user plumbing, not OAuth
    monkeypatch.setattr(tr, "_check_server_oauth_enforcement", AsyncMock(return_value=None))

    # No proxy user header, no authorization - falls through to permissive mode
    scope = _make_scope("/servers/1/mcp")
    sent = []

    async def send(msg):
        sent.append(msg)

    result = await streamable_http_auth(scope, None, send)
    assert result is True  # Permissive mode allows
    assert sent == []


# ---------------------------------------------------------------------------
# get_prompt: _meta extraction from request context (Lines 906-907)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_prompt_with_meta_from_request_context(monkeypatch):
    """Test get_prompt extracts _meta from request context (lines 906-907)."""
    # Third-Party
    from mcp.types import PromptMessage, TextContent

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import get_prompt, mcp_app, prompt_service, types, user_context_var

    mock_db = MagicMock()
    mock_message = PromptMessage(role="user", content=TextContent(type="text", text="test"))
    mock_result = MagicMock()
    mock_result.messages = [mock_message]
    mock_result.description = "desc"

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    captured_kwargs = {}

    async def mock_get_prompt(db, prompt_id, arguments=None, **kwargs):
        captured_kwargs.update(kwargs)
        return mock_result

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(prompt_service, "get_prompt", mock_get_prompt)

    # Mock request_context to have meta
    mock_ctx = MagicMock()
    mock_meta = MagicMock()
    mock_meta.model_dump.return_value = {"progressToken": "tok123"}
    mock_ctx.meta = mock_meta
    type(mcp_app).request_context = property(lambda self: mock_ctx)

    user_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})
    try:
        result = await get_prompt("test_prompt")
        assert isinstance(result, types.GetPromptResult)
        assert captured_kwargs["_meta_data"] == {"progressToken": "tok123"}
    finally:
        user_context_var.reset(user_token)
        type(mcp_app).request_context = property(lambda self: (_ for _ in ()).throw(LookupError))


@pytest.mark.asyncio
async def test_get_prompt_with_request_context_no_meta(monkeypatch):
    """Test get_prompt handles an active request context without meta (line 906->912)."""
    # Third-Party
    from mcp.types import PromptMessage, TextContent

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import get_prompt, mcp_app, prompt_service, user_context_var

    mock_db = MagicMock()
    mock_message = PromptMessage(role="user", content=TextContent(type="text", text="test"))
    mock_result = MagicMock()
    mock_result.messages = [mock_message]
    mock_result.description = "desc"

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    captured_kwargs = {}

    async def mock_get_prompt(db, prompt_id, arguments=None, **kwargs):
        captured_kwargs.update(kwargs)
        return mock_result

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(prompt_service, "get_prompt", mock_get_prompt)

    mock_ctx = MagicMock()
    mock_ctx.meta = None
    type(mcp_app).request_context = property(lambda self: mock_ctx)

    user_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})
    try:
        await get_prompt("test_prompt")
        assert captured_kwargs["_meta_data"] is None
    finally:
        user_context_var.reset(user_token)
        type(mcp_app).request_context = property(lambda self: (_ for _ in ()).throw(LookupError))


# ---------------------------------------------------------------------------
# read_resource: _meta extraction from request context (Lines 1030-1031)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_resource_with_meta_from_request_context(monkeypatch):
    """Test read_resource extracts _meta from request context (lines 1030-1031)."""
    # Third-Party
    from pydantic import AnyUrl

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import mcp_app, read_resource, resource_service, user_context_var

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_result.text = "resource content"
    mock_result.blob = None

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    captured_kwargs = {}

    async def mock_read_resource(db, resource_uri, **kwargs):
        captured_kwargs.update(kwargs)
        return mock_result

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(resource_service, "read_resource", mock_read_resource)

    # Mock request_context to have meta
    mock_ctx = MagicMock()
    mock_meta = MagicMock()
    mock_meta.model_dump.return_value = {"progressToken": "tok456"}
    mock_ctx.meta = mock_meta
    type(mcp_app).request_context = property(lambda self: mock_ctx)

    user_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})
    try:
        test_uri = AnyUrl("file:///test.txt")
        result = await read_resource(test_uri)
        assert result == "resource content"
        assert captured_kwargs["meta_data"] == {"progressToken": "tok456"}
    finally:
        user_context_var.reset(user_token)
        type(mcp_app).request_context = property(lambda self: (_ for _ in ()).throw(LookupError))


@pytest.mark.asyncio
async def test_read_resource_with_request_context_no_meta(monkeypatch):
    """Test read_resource handles an active request context without meta (line 1030->1036)."""
    # Third-Party
    from pydantic import AnyUrl

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import mcp_app, read_resource, resource_service, user_context_var

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_result.text = "resource content"
    mock_result.blob = None

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    captured_kwargs = {}

    async def mock_read_resource(db, resource_uri, **kwargs):
        captured_kwargs.update(kwargs)
        return mock_result

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(resource_service, "read_resource", mock_read_resource)

    mock_ctx = MagicMock()
    mock_ctx.meta = None
    type(mcp_app).request_context = property(lambda self: mock_ctx)

    user_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})
    try:
        test_uri = AnyUrl("file:///test.txt")
        await read_resource(test_uri)
        assert captured_kwargs["meta_data"] is None
    finally:
        user_context_var.reset(user_token)
        type(mcp_app).request_context = property(lambda self: (_ for _ in ()).throw(LookupError))


# ---------------------------------------------------------------------------
# _convert_meta: model_dump return path (Line 677)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# list_tools: team-scoped user (Line 791->794 - token_teams is NOT None)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tools_team_scoped_user(monkeypatch):
    """Test list_tools with team-scoped user context (token_teams not None) (line 791->794)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_tools, server_id_var, tool_service, user_context_var

    mock_db = MagicMock()
    mock_tool = MagicMock()
    mock_tool.name = "team_tool"
    mock_tool.title = None
    mock_tool.description = "team tool desc"
    mock_tool.input_schema = {"type": "object"}
    mock_tool.output_schema = None
    mock_tool.annotations = {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    captured_kwargs = {}

    async def mock_list_tools(db, include_inactive=False, limit=0, **kwargs):
        captured_kwargs.update(kwargs)
        return ([mock_tool], None)

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "list_tools", mock_list_tools)

    server_token = server_id_var.set(None)
    user_token = user_context_var.set({"email": "user@test.com", "teams": ["team-1"], "is_admin": False})
    try:
        result = await list_tools()
        assert len(result) == 1
        assert captured_kwargs["token_teams"] == ["team-1"]
    finally:
        server_id_var.reset(server_token)
        user_context_var.reset(user_token)


# ---------------------------------------------------------------------------
# list_prompts: team-scoped user (Line 843->846)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_prompts_team_scoped_user(monkeypatch):
    """Test list_prompts with team-scoped user (token_teams not None) (line 843->846)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_prompts, prompt_service, server_id_var, user_context_var

    mock_db = MagicMock()
    mock_prompt = MagicMock()
    mock_prompt.name = "team_prompt"
    mock_prompt.title = None
    mock_prompt.description = "team prompt desc"
    mock_prompt.arguments = []

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    captured_kwargs = {}

    async def mock_list_prompts(db, include_inactive=False, limit=0, **kwargs):
        captured_kwargs.update(kwargs)
        return ([mock_prompt], None)

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(prompt_service, "list_prompts", mock_list_prompts)

    server_token = server_id_var.set(None)
    user_token = user_context_var.set({"email": "user@test.com", "teams": ["team-1"], "is_admin": False})
    try:
        result = await list_prompts()
        assert len(result) == 1
        assert captured_kwargs["token_teams"] == ["team-1"]
    finally:
        server_id_var.reset(server_token)
        user_context_var.reset(user_token)


# ---------------------------------------------------------------------------
# list_resources: team-scoped user (Line 968->971)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_resources_team_scoped_user(monkeypatch):
    """Test list_resources with team-scoped user (token_teams not None) (line 968->971)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_resources, resource_service, server_id_var, user_context_var

    mock_db = MagicMock()
    mock_resource = MagicMock()
    mock_resource.uri = "file:///team.txt"
    mock_resource.name = "team resource"
    mock_resource.title = None
    mock_resource.description = "team desc"
    mock_resource.mime_type = "text/plain"

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    captured_kwargs = {}

    async def mock_list_resources(db, include_inactive=False, limit=0, **kwargs):
        captured_kwargs.update(kwargs)
        return ([mock_resource], None)

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(resource_service, "list_resources", mock_list_resources)

    server_token = server_id_var.set(None)
    user_token = user_context_var.set({"email": "user@test.com", "teams": ["team-1"], "is_admin": False})
    try:
        result = await list_resources()
        assert len(result) == 1
        assert captured_kwargs["token_teams"] == ["team-1"]
    finally:
        server_id_var.reset(server_token)
        user_context_var.reset(user_token)


@pytest.mark.asyncio
async def test_call_tool_meta_not_convertible(monkeypatch):
    """Test _convert_meta returns None when meta is not dict, None, or has model_dump (line 677)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_content = MagicMock()
    mock_content.type = "text"
    mock_content.text = "hello"
    mock_content.annotations = None
    # Meta is not dict, not None, and has no model_dump
    meta_obj = MagicMock(spec=[])  # Empty spec - no model_dump
    mock_content.meta = meta_obj
    mock_result.content = [mock_content]
    mock_result.structured_content = None
    mock_result.model_dump = lambda by_alias=True: {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    result = await call_tool("mytool", {})
    assert isinstance(result, list)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# ASGI helpers for handle_streamable_http tests
# ---------------------------------------------------------------------------


def _make_receive(body_bytes: bytes):
    """Return an async receive callable yielding a single http.request message."""
    called = False

    async def receive():
        nonlocal called
        if not called:
            called = True
            return {"type": "http.request", "body": body_bytes, "more_body": False}
        return {"type": "http.disconnect"}

    return receive


def _make_receive_disconnect():
    """Return an async receive callable yielding http.disconnect immediately."""

    async def receive():
        return {"type": "http.disconnect"}

    return receive


def _make_receive_sequence(messages):
    """Return an async receive callable yielding a fixed sequence then disconnect."""
    idx = 0

    async def receive():
        nonlocal idx
        if idx < len(messages):
            msg = messages[idx]
            idx += 1
            return msg
        return {"type": "http.disconnect"}

    return receive


def _make_send_collector():
    """Return (send_fn, messages_list) for capturing ASGI send calls."""
    messages = []

    async def send(msg):
        messages.append(msg)

    return send, messages


# ---------------------------------------------------------------------------
# Group 1: call_tool session affinity (lines 546-623)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_tool_session_affinity_forwarded_success(monkeypatch):
    """Test call_tool forwards to owner worker via session pool and returns unstructured content."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, request_headers_var, types, user_context_var

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)

    # Set request headers with a session id
    h_token = request_headers_var.set({"mcp-session-id": "abc-123-valid-session"})
    u_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})

    mock_pool = MagicMock()
    mock_pool.forward_request_to_owner = AsyncMock(return_value={"result": {"content": [{"type": "text", "text": "forwarded result"}]}})
    mock_pool.register_session_mapping = AsyncMock()

    mock_cache = AsyncMock()
    mock_cache.get = AsyncMock(return_value={"status": "active", "gateway": {"url": "http://gw:9000", "id": "g1", "transport": "streamablehttp"}})

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    try:
        with (
            patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
            patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
            patch("mcpgateway.cache.tool_lookup_cache.tool_lookup_cache", mock_cache),
        ):
            result = await call_tool("my_tool", {"arg": "val"})
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], types.TextContent)
        assert result[0].text == "forwarded result"
    finally:
        request_headers_var.reset(h_token)
        user_context_var.reset(u_token)


@pytest.mark.asyncio
async def test_call_tool_session_affinity_forwarded_with_structured(monkeypatch):
    """Test call_tool returns tuple when forwarded response has structuredContent."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, request_headers_var, user_context_var

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)

    h_token = request_headers_var.set({"mcp-session-id": "abc-123-valid-session"})
    u_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})

    mock_pool = MagicMock()
    mock_pool.forward_request_to_owner = AsyncMock(return_value={"result": {"content": [{"type": "text", "text": "r"}], "structuredContent": {"key": "val"}}})
    mock_pool.register_session_mapping = AsyncMock()

    mock_cache = AsyncMock()
    mock_cache.get = AsyncMock(return_value=None)

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    try:
        with (
            patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
            patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
            patch("mcpgateway.cache.tool_lookup_cache.tool_lookup_cache", mock_cache),
        ):
            result = await call_tool("my_tool", {})
        assert isinstance(result, tuple)
        assert result[1] == {"key": "val"}
    finally:
        request_headers_var.reset(h_token)
        user_context_var.reset(u_token)


@pytest.mark.asyncio
async def test_call_tool_session_affinity_forwarded_error(monkeypatch):
    """Test call_tool raises when forwarded response contains an error."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, request_headers_var, user_context_var

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)

    h_token = request_headers_var.set({"mcp-session-id": "abc-123-valid-session"})
    u_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})

    mock_pool = MagicMock()
    mock_pool.forward_request_to_owner = AsyncMock(return_value={"error": {"message": "remote error"}})
    mock_pool.register_session_mapping = AsyncMock()

    mock_cache = AsyncMock()
    mock_cache.get = AsyncMock(return_value=None)

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    try:
        with (
            patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
            patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
            patch("mcpgateway.cache.tool_lookup_cache.tool_lookup_cache", mock_cache),
        ):
            # Should raise because the forwarded response has error
            # But the exception is caught and re-raised by the outer try in call_tool
            with pytest.raises(Exception, match="remote error"):
                await call_tool("my_tool", {})
    finally:
        request_headers_var.reset(h_token)
        user_context_var.reset(u_token)


@pytest.mark.asyncio
async def test_call_tool_session_affinity_rehydrate_image(monkeypatch):
    """Test _rehydrate_content_items converts image items."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import (
        call_tool,
        request_headers_var,
        types,
        user_context_var,
    )

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)

    h_token = request_headers_var.set({"mcp-session-id": "abc-123-valid-session"})
    u_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})

    mock_pool = MagicMock()
    mock_pool.forward_request_to_owner = AsyncMock(return_value={"result": {"content": [{"type": "image", "data": "abc", "mimeType": "image/png"}]}})
    mock_pool.register_session_mapping = AsyncMock()

    mock_cache = AsyncMock()
    mock_cache.get = AsyncMock(return_value=None)

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    try:
        with (
            patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
            patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
            patch("mcpgateway.cache.tool_lookup_cache.tool_lookup_cache", mock_cache),
        ):
            result = await call_tool("my_tool", {})
        assert isinstance(result[0], types.ImageContent)
    finally:
        request_headers_var.reset(h_token)
        user_context_var.reset(u_token)


@pytest.mark.asyncio
async def test_call_tool_session_affinity_rehydrate_audio(monkeypatch):
    """Test _rehydrate_content_items converts audio items."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import (
        call_tool,
        request_headers_var,
        types,
        user_context_var,
    )

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)

    h_token = request_headers_var.set({"mcp-session-id": "abc-123-valid-session"})
    u_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})

    mock_pool = MagicMock()
    mock_pool.forward_request_to_owner = AsyncMock(return_value={"result": {"content": [{"type": "audio", "data": "aud", "mimeType": "audio/mp3"}]}})
    mock_pool.register_session_mapping = AsyncMock()

    mock_cache = AsyncMock()
    mock_cache.get = AsyncMock(return_value=None)

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    try:
        with (
            patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
            patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
            patch("mcpgateway.cache.tool_lookup_cache.tool_lookup_cache", mock_cache),
        ):
            result = await call_tool("my_tool", {})
        assert isinstance(result[0], types.AudioContent)
    finally:
        request_headers_var.reset(h_token)
        user_context_var.reset(u_token)


@pytest.mark.asyncio
async def test_call_tool_session_affinity_rehydrate_unknown_and_invalid(monkeypatch):
    """Test _rehydrate_content_items handles unknown type and invalid (non-dict) items."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, request_headers_var, types, user_context_var

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)

    h_token = request_headers_var.set({"mcp-session-id": "abc-123-valid-session"})
    u_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})

    mock_pool = MagicMock()
    mock_pool.forward_request_to_owner = AsyncMock(
        return_value={
            "result": {
                "content": [
                    {"type": "unknown_type", "data": "x"},
                    "not_a_dict",  # invalid item - should be skipped
                ]
            }
        }
    )
    mock_pool.register_session_mapping = AsyncMock()

    mock_cache = AsyncMock()
    mock_cache.get = AsyncMock(return_value=None)

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    try:
        with (
            patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
            patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
            patch("mcpgateway.cache.tool_lookup_cache.tool_lookup_cache", mock_cache),
        ):
            result = await call_tool("my_tool", {})
        # Unknown type is converted to TextContent, non-dict is skipped
        assert len(result) == 1
        assert isinstance(result[0], types.TextContent)
    finally:
        request_headers_var.reset(h_token)
        user_context_var.reset(u_token)


@pytest.mark.asyncio
async def test_call_tool_session_affinity_invalid_session_id_fallthrough(monkeypatch):
    """Test call_tool falls through to local execution when session ID is invalid."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, request_headers_var, tool_service, user_context_var

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)

    h_token = request_headers_var.set({"mcp-session-id": "invalid-id"})
    u_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=False)

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_content = MagicMock()
    mock_content.type = "text"
    mock_content.text = "local result"
    mock_content.annotations = None
    mock_content.meta = None
    mock_result.content = [mock_content]
    mock_result.structured_content = None
    mock_result.model_dump = lambda by_alias=True: {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    try:
        with patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class):
            result = await call_tool("my_tool", {})
        assert isinstance(result, list)
        assert result[0].text == "local result"
    finally:
        request_headers_var.reset(h_token)
        user_context_var.reset(u_token)


@pytest.mark.asyncio
async def test_call_tool_session_affinity_pool_not_initialized(monkeypatch):
    """Test call_tool falls through when pool is not initialized (RuntimeError)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, request_headers_var, tool_service, user_context_var

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)

    h_token = request_headers_var.set({"mcp-session-id": "abc-123-valid-session"})
    u_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_content = MagicMock()
    mock_content.type = "text"
    mock_content.text = "local fallback"
    mock_content.annotations = None
    mock_content.meta = None
    mock_result.content = [mock_content]
    mock_result.structured_content = None
    mock_result.model_dump = lambda by_alias=True: {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    try:
        with (
            patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", side_effect=RuntimeError("not init")),
            patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
        ):
            result = await call_tool("my_tool", {})
        assert isinstance(result, list)
        assert result[0].text == "local fallback"
    finally:
        request_headers_var.reset(h_token)
        user_context_var.reset(u_token)


@pytest.mark.asyncio
async def test_call_tool_session_affinity_registration_failure(monkeypatch, caplog):
    """Test call_tool logs error when session mapping registration fails."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, request_headers_var, user_context_var

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)

    h_token = request_headers_var.set({"mcp-session-id": "abc-123-valid-session"})
    u_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})

    mock_pool = MagicMock()
    mock_pool.forward_request_to_owner = AsyncMock(return_value={"result": {"content": [{"type": "text", "text": "ok"}]}})
    mock_pool.register_session_mapping = AsyncMock(side_effect=Exception("register fail"))

    mock_cache = AsyncMock()
    mock_cache.get = AsyncMock(return_value={"status": "active", "gateway": {"url": "http://gw:9000", "id": "g1", "transport": "streamablehttp"}})

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    try:
        with (
            patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
            patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
            patch("mcpgateway.cache.tool_lookup_cache.tool_lookup_cache", mock_cache),
            caplog.at_level("ERROR"),
        ):
            result = await call_tool("my_tool", {})
        assert isinstance(result, list)
        assert "Failed to pre-register session mapping" in caplog.text
    finally:
        request_headers_var.reset(h_token)
        user_context_var.reset(u_token)


@pytest.mark.asyncio
async def test_call_tool_session_affinity_cached_gateway_missing(monkeypatch):
    """Session mapping pre-registration should be skipped when cached gateway info is missing (line 564->573)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, request_headers_var, types, user_context_var

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)

    h_token = request_headers_var.set({"mcp-session-id": "abc-123-valid-session"})
    u_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})

    mock_pool = MagicMock()
    mock_pool.forward_request_to_owner = AsyncMock(return_value={"result": {"content": [{"type": "text", "text": "ok"}]}})
    mock_pool.register_session_mapping = AsyncMock()

    mock_cache = AsyncMock()
    mock_cache.get = AsyncMock(return_value={"status": "active", "gateway": None})

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    try:
        with (
            patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
            patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
            patch("mcpgateway.cache.tool_lookup_cache.tool_lookup_cache", mock_cache),
        ):
            result = await call_tool("my_tool", {})
        assert isinstance(result, list)
        assert isinstance(result[0], types.TextContent)
        mock_pool.register_session_mapping.assert_not_called()
    finally:
        request_headers_var.reset(h_token)
        user_context_var.reset(u_token)


@pytest.mark.asyncio
async def test_call_tool_session_affinity_cached_gateway_no_url(monkeypatch):
    """Session mapping pre-registration should be skipped when cached gateway URL is missing (line 568->573)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, request_headers_var, types, user_context_var

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)

    h_token = request_headers_var.set({"mcp-session-id": "abc-123-valid-session"})
    u_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})

    mock_pool = MagicMock()
    mock_pool.forward_request_to_owner = AsyncMock(return_value={"result": {"content": [{"type": "text", "text": "ok"}]}})
    mock_pool.register_session_mapping = AsyncMock()

    mock_cache = AsyncMock()
    mock_cache.get = AsyncMock(return_value={"status": "active", "gateway": {"url": None, "id": "g1", "transport": "streamablehttp"}})

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    try:
        with (
            patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
            patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
            patch("mcpgateway.cache.tool_lookup_cache.tool_lookup_cache", mock_cache),
        ):
            result = await call_tool("my_tool", {})
        assert isinstance(result, list)
        assert isinstance(result[0], types.TextContent)
        mock_pool.register_session_mapping.assert_not_called()
    finally:
        request_headers_var.reset(h_token)
        user_context_var.reset(u_token)


@pytest.mark.asyncio
async def test_call_tool_session_affinity_forwarded_none_falls_back_local(monkeypatch):
    """When forwarding returns None, call_tool should fall back to local tool execution (line 577->625)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, request_headers_var, tool_service, types, user_context_var

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)

    h_token = request_headers_var.set({"mcp-session-id": "abc-123-valid-session"})
    u_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})

    mock_pool = MagicMock()
    mock_pool.forward_request_to_owner = AsyncMock(return_value=None)
    mock_pool.register_session_mapping = AsyncMock()

    mock_cache = AsyncMock()
    mock_cache.get = AsyncMock(return_value=None)

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_content = MagicMock()
    mock_content.type = "text"
    mock_content.text = "local fallback"
    mock_content.annotations = None
    mock_content.meta = None
    mock_result.content = [mock_content]
    mock_result.structured_content = None
    mock_result.model_dump = lambda by_alias=True: {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    try:
        with (
            patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
            patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
            patch("mcpgateway.cache.tool_lookup_cache.tool_lookup_cache", mock_cache),
        ):
            result = await call_tool("my_tool", {})
        assert isinstance(result, list)
        assert result[0].text == "local fallback"
        assert isinstance(result[0], types.TextContent)
    finally:
        request_headers_var.reset(h_token)
        user_context_var.reset(u_token)


@pytest.mark.asyncio
async def test_call_tool_session_affinity_forwarded_non_list_content(monkeypatch):
    """_rehydrate_content_items should return [] when forwarded content is not a list (line 593)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, request_headers_var, user_context_var

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)

    h_token = request_headers_var.set({"mcp-session-id": "abc-123-valid-session"})
    u_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})

    mock_pool = MagicMock()
    mock_pool.forward_request_to_owner = AsyncMock(return_value={"result": {"content": {"type": "text", "text": "not-a-list"}}})
    mock_pool.register_session_mapping = AsyncMock()

    mock_cache = AsyncMock()
    mock_cache.get = AsyncMock(return_value=None)

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    try:
        with (
            patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
            patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
            patch("mcpgateway.cache.tool_lookup_cache.tool_lookup_cache", mock_cache),
        ):
            result = await call_tool("my_tool", {})
        assert result == []
    finally:
        request_headers_var.reset(h_token)
        user_context_var.reset(u_token)


@pytest.mark.asyncio
async def test_call_tool_session_affinity_rehydrate_resource_types_fallback(monkeypatch):
    """Invalid resource_link/resource payloads should fall back to TextContent (lines 607, 609, 612-613)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, request_headers_var, types, user_context_var

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)

    h_token = request_headers_var.set({"mcp-session-id": "abc-123-valid-session"})
    u_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})

    mock_pool = MagicMock()
    mock_pool.forward_request_to_owner = AsyncMock(
        return_value={
            "result": {
                "content": [
                    {"type": "resource_link"},  # missing required fields -> validation error
                    {"type": "resource"},  # missing required fields -> validation error
                ]
            }
        }
    )
    mock_pool.register_session_mapping = AsyncMock()

    mock_cache = AsyncMock()
    mock_cache.get = AsyncMock(return_value=None)

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    try:
        with (
            patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
            patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
            patch("mcpgateway.cache.tool_lookup_cache.tool_lookup_cache", mock_cache),
        ):
            result = await call_tool("my_tool", {})
        assert len(result) == 2
        assert all(isinstance(item, types.TextContent) for item in result)
    finally:
        request_headers_var.reset(h_token)
        user_context_var.reset(u_token)


# ---------------------------------------------------------------------------
# Group 2: SessionManagerWrapper Redis init (line 1259)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_manager_wrapper_redis_event_store(monkeypatch):
    """Test SessionManagerWrapper uses RedisEventStore when redis is configured and stateful."""

    captured_config = {}

    def capture_manager(**kwargs):
        captured_config.update(kwargs)
        dummy = MagicMock()
        dummy.run = MagicMock(return_value=asynccontextmanager(lambda: (yield dummy))())
        return dummy

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.json_response_enabled", False)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.cache_type", "redis")
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.redis_url", "redis://localhost:6379")
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.streamable_http_max_events_per_stream", 50)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.streamable_http_event_ttl", 1800)
    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", capture_manager)

    SessionManagerWrapper()

    assert captured_config["stateless"] is False
    assert captured_config["event_store"] is not None
    # First-Party
    from mcpgateway.transports.redis_event_store import RedisEventStore

    assert isinstance(captured_config["event_store"], RedisEventStore)


@pytest.mark.asyncio
async def test_session_manager_wrapper_rust_event_store(monkeypatch):
    """SessionManagerWrapper should use RustEventStore when the Rust event-store flag is enabled."""

    captured_config = {}

    def capture_manager(**kwargs):
        captured_config.update(kwargs)
        dummy = MagicMock()
        dummy.run = MagicMock(return_value=asynccontextmanager(lambda: (yield dummy))())
        return dummy

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.json_response_enabled", False)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.experimental_rust_mcp_runtime_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.experimental_rust_mcp_session_auth_reuse_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.experimental_rust_mcp_event_store_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.streamable_http_max_events_per_stream", 75)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.streamable_http_event_ttl", 2700)
    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", capture_manager)

    SessionManagerWrapper()

    assert captured_config["stateless"] is False
    assert isinstance(captured_config["event_store"], tr.RustEventStore)
    assert captured_config["event_store"].max_events_per_stream == 75
    assert captured_config["event_store"].ttl == 2700


@pytest.mark.asyncio
async def test_session_manager_wrapper_redis_event_store_when_rust_event_store_disabled(monkeypatch):
    """SessionManagerWrapper should fall back to RedisEventStore when Rust event store is disabled."""

    captured_config = {}

    def capture_manager(**kwargs):
        captured_config.update(kwargs)
        dummy = MagicMock()
        dummy.run = MagicMock(return_value=asynccontextmanager(lambda: (yield dummy))())
        return dummy

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.json_response_enabled", False)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.experimental_rust_mcp_runtime_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.experimental_rust_mcp_event_store_enabled", False)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.cache_type", "redis")
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.redis_url", "redis://localhost:6379/0")
    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", capture_manager)

    SessionManagerWrapper()

    # First-Party
    from mcpgateway.transports.redis_event_store import RedisEventStore

    assert isinstance(captured_config["event_store"], RedisEventStore)


@pytest.mark.asyncio
async def test_session_manager_wrapper_falls_back_to_python_event_store_when_session_auth_reuse_disabled(monkeypatch):
    """SessionManagerWrapper should not activate RustEventStore when public session auth reuse is disabled."""

    captured_config = {}

    def capture_manager(**kwargs):
        captured_config.update(kwargs)
        dummy = MagicMock()
        dummy.run = MagicMock(return_value=asynccontextmanager(lambda: (yield dummy))())
        return dummy

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.json_response_enabled", False)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.experimental_rust_mcp_runtime_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.experimental_rust_mcp_session_auth_reuse_enabled", False)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.experimental_rust_mcp_event_store_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.cache_type", "redis")
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.redis_url", "redis://localhost:6379/0")
    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", capture_manager)

    SessionManagerWrapper()

    # First-Party
    from mcpgateway.transports.redis_event_store import RedisEventStore

    assert isinstance(captured_config["event_store"], RedisEventStore)


# ---------------------------------------------------------------------------
# Group 3: Header parsing edge cases (lines 1344-1348)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_streamable_http_non_tuple_header_skipped(monkeypatch):
    """Test handle_streamable_http skips non-tuple header items (line 1344)."""

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            await send_func({"type": "http.response.start", "status": 200, "headers": []})
            await send_func({"type": "http.response.body", "body": b"ok"})

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/mcp",
        "modified_path": "/mcp",
        "query_string": b"",
        "headers": [
            "not_a_tuple",  # Should be skipped
            (b"content-type", b"application/json"),
        ],
    }
    await wrapper.handle_streamable_http(scope, _make_receive(b""), send)
    await wrapper.shutdown()
    assert any(m["type"] == "http.response.start" for m in messages)


@pytest.mark.asyncio
async def test_handle_streamable_http_non_bytes_header_skipped(monkeypatch):
    """Test handle_streamable_http skips headers with non-bytes key/value (line 1347)."""

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            await send_func({"type": "http.response.start", "status": 200, "headers": []})
            await send_func({"type": "http.response.body", "body": b"ok"})

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/mcp",
        "modified_path": "/mcp",
        "query_string": b"",
        "headers": [
            ("string_key", "string_value"),  # Non-bytes - should be skipped
            (b"content-type", b"application/json"),
        ],
    }
    await wrapper.handle_streamable_http(scope, _make_receive(b""), send)
    await wrapper.shutdown()
    assert any(m["type"] == "http.response.start" for m in messages)


# ---------------------------------------------------------------------------
# Group 4: Session ID validation (lines 1367-1375)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_streamable_http_invalid_session_id_reset(monkeypatch):
    """Test handle_streamable_http resets invalid session ID to not-provided (line 1372-1373)."""

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            await send_func({"type": "http.response.start", "status": 200, "headers": []})
            await send_func({"type": "http.response.body", "body": b"ok"})

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", False)

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=False)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    scope = _make_scope("/mcp", headers=[(b"mcp-session-id", b"bad-id")])

    with patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class):
        await wrapper.handle_streamable_http(scope, _make_receive(b""), send)

    await wrapper.shutdown()
    assert any(m["type"] == "http.response.start" for m in messages)


@pytest.mark.asyncio
async def test_handle_streamable_http_session_validation_exception(monkeypatch):
    """Test handle_streamable_http handles exception during session validation (line 1374-1375)."""

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            await send_func({"type": "http.response.start", "status": 200, "headers": []})
            await send_func({"type": "http.response.body", "body": b"ok"})

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", False)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    scope = _make_scope("/mcp", headers=[(b"mcp-session-id", b"some-id")])

    # Trigger the broad Exception handler by making session id validation raise
    with patch("mcpgateway.services.mcp_session_pool.MCPSessionPool.is_valid_mcp_session_id", side_effect=Exception("boom")):
        await wrapper.handle_streamable_http(scope, _make_receive(b""), send)

    await wrapper.shutdown()
    assert any(m["type"] == "http.response.start" for m in messages)


# ---------------------------------------------------------------------------
# Group 5: Internally forwarded paths (lines 1380-1464)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forwarded_non_post_returns_200(monkeypatch):
    """Test forwarded non-POST request returns 200 OK (line 1385-1389)."""

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            raise AssertionError("Should not reach SDK")

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    scope = _make_scope("/mcp", method="DELETE", headers=[(b"x-forwarded-internally", b"true")])

    await wrapper.handle_streamable_http(scope, _make_receive(b""), send)
    await wrapper.shutdown()
    assert messages[0]["status"] == 200
    assert messages[1]["body"] == b'{"jsonrpc":"2.0","result":{}}'


@pytest.mark.asyncio
async def test_forwarded_post_routes_to_rpc(monkeypatch):
    """Test forwarded POST routes to /rpc via httpx (lines 1393-1461)."""
    # Third-Party

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            raise AssertionError("Should not reach SDK")

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    body = b'{"jsonrpc":"2.0","method":"tools/list","id":1}'
    scope = _make_scope(
        "/mcp",
        method="POST",
        headers=[
            (b"x-forwarded-internally", b"true"),
            (b"mcp-session-id", b"sess-123"),
        ],
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'{"jsonrpc":"2.0","result":{"tools":[]},"id":1}'

    with patch("mcpgateway.transports.streamablehttp_transport.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        await wrapper.handle_streamable_http(scope, _make_receive(body), send)

    await wrapper.shutdown()
    assert messages[0]["status"] == 200


@pytest.mark.asyncio
async def test_forwarded_post_routes_to_rpc_multipart_body_and_auth_header(monkeypatch):
    """Cover multipart request body handling and auth header copy for forwarded internal requests (lines 1396-1460)."""

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            raise AssertionError("Should not reach SDK")

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    part1 = b'{"jsonrpc":"2.0","method":"tools/l'
    part2 = b'ist","id":1}'
    scope = _make_scope(
        "/mcp",
        method="POST",
        headers=[
            (b"x-forwarded-internally", b"true"),
            (b"authorization", b"Bearer abc"),
        ],
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'{"jsonrpc":"2.0","result":{},"id":1}'

    receive = _make_receive_sequence(
        [
            {"type": "http.unknown"},
            {"type": "http.request", "body": part1, "more_body": True},
            {"type": "http.request", "body": part2, "more_body": False},
        ]
    )

    with patch("mcpgateway.transports.streamablehttp_transport.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        await wrapper.handle_streamable_http(scope, receive, send)

    await wrapper.shutdown()
    assert messages[0]["status"] == 200
    assert mock_client.post.call_args.kwargs["headers"]["authorization"] == "Bearer abc"
    # No client mcp-session-id was provided -> should not be echoed back
    assert b"mcp-session-id" not in [h[0] for h in messages[0]["headers"]]


@pytest.mark.asyncio
async def test_forwarded_post_empty_body_returns_202(monkeypatch):
    """Test forwarded POST with empty body returns 202 (line 1406-1410)."""

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            raise AssertionError("Should not reach SDK")

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    scope = _make_scope("/mcp", method="POST", headers=[(b"x-forwarded-internally", b"true")])

    await wrapper.handle_streamable_http(scope, _make_receive(b""), send)
    await wrapper.shutdown()
    assert messages[0]["status"] == 202


@pytest.mark.asyncio
async def test_forwarded_post_notification_returns_202(monkeypatch):
    """Test forwarded POST with notification method returns 202 (line 1417-1421)."""

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            raise AssertionError("Should not reach SDK")

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    body = b'{"jsonrpc":"2.0","method":"notifications/initialized"}'
    scope = _make_scope("/mcp", method="POST", headers=[(b"x-forwarded-internally", b"true")])

    await wrapper.handle_streamable_http(scope, _make_receive(body), send)
    await wrapper.shutdown()
    assert messages[0]["status"] == 202


@pytest.mark.asyncio
async def test_forwarded_post_disconnect_returns_early(monkeypatch):
    """Test forwarded POST with disconnect during body read returns early (line 1402-1403)."""

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            raise AssertionError("Should not reach SDK")

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    scope = _make_scope("/mcp", method="POST", headers=[(b"x-forwarded-internally", b"true")])

    await wrapper.handle_streamable_http(scope, _make_receive_disconnect(), send)
    await wrapper.shutdown()
    assert messages == []  # No response sent


@pytest.mark.asyncio
async def test_forwarded_post_exception_falls_through(monkeypatch):
    """Test forwarded POST exception falls through to SDK handling (line 1463-1465)."""

    sdk_called = False

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            nonlocal sdk_called
            sdk_called = True
            await send_func({"type": "http.response.start", "status": 200, "headers": []})
            await send_func({"type": "http.response.body", "body": b"sdk"})

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    body = b'{"jsonrpc":"2.0","method":"tools/list","id":1}'
    scope = _make_scope("/mcp", method="POST", headers=[(b"x-forwarded-internally", b"true")])

    with patch("mcpgateway.transports.streamablehttp_transport.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("httpx fail"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        await wrapper.handle_streamable_http(scope, _make_receive(body), send)

    await wrapper.shutdown()
    assert sdk_called


@pytest.mark.asyncio
async def test_forwarded_post_injects_server_id_from_url(monkeypatch):
    """Test internally-forwarded POST injects server_id when params dict is missing.

    Verifies server_id extraction from /servers/{server_id}/mcp URL pattern is
    injected into newly-created params dict before forwarding to /rpc.
    """
    # Third-Party
    import orjson

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            raise AssertionError("Should not reach SDK")

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.services.server_service.ServerService.entity_exists", AsyncMock(return_value=True))
    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    server_id = "abc-123-def-456"  # Valid hex format matching regex pattern
    send, messages = _make_send_collector()
    # Body WITHOUT params field - this triggers line 1865 (params dict creation)
    body = b'{"jsonrpc":"2.0","method":"tools/list","id":1}'
    scope = _make_scope(
        f"/servers/{server_id}/mcp",
        method="POST",
        headers=[(b"x-forwarded-internally", b"true")],
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'{"jsonrpc":"2.0","result":{"tools":[]},"id":1}'

    with patch("mcpgateway.transports.streamablehttp_transport.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        await wrapper.handle_streamable_http(scope, _make_receive(body), send)

        # Verify the POST to /rpc includes server_id in params (created if missing)
        mock_client.post.assert_called_once()
        posted_content = mock_client.post.call_args.kwargs["content"]
        posted_json = orjson.loads(posted_content)

        assert "params" in posted_json, "params dict should be created when missing"
        assert posted_json["params"]["server_id"] == server_id

    await wrapper.shutdown()
    assert messages[0]["status"] == 200


@pytest.mark.asyncio
async def test_forwarded_post_injects_server_id_with_existing_params(monkeypatch):
    """Test internally-forwarded POST injects server_id into existing params dict.

    Verifies that when params already contains other keys, server_id is merged
    in without overwriting existing values.
    """
    # Third-Party
    import orjson

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            raise AssertionError("Should not reach SDK")

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.services.server_service.ServerService.entity_exists", AsyncMock(return_value=True))
    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    server_id = "abc-123-def-456"
    send, messages = _make_send_collector()
    # Body WITH existing params containing other keys
    body = b'{"jsonrpc":"2.0","method":"tools/list","params":{"cursor":"page2","extra":"value"},"id":1}'
    scope = _make_scope(
        f"/servers/{server_id}/mcp",
        method="POST",
        headers=[(b"x-forwarded-internally", b"true")],
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'{"jsonrpc":"2.0","result":{"tools":[]},"id":1}'

    with patch("mcpgateway.transports.streamablehttp_transport.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        await wrapper.handle_streamable_http(scope, _make_receive(body), send)

        mock_client.post.assert_called_once()
        posted_content = mock_client.post.call_args.kwargs["content"]
        posted_json = orjson.loads(posted_content)

        assert posted_json["params"]["server_id"] == server_id
        assert posted_json["params"]["cursor"] == "page2", "Existing params should be preserved"
        assert posted_json["params"]["extra"] == "value", "Existing params should be preserved"

    await wrapper.shutdown()
    assert messages[0]["status"] == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params_value,params_json",
    [
        ("null", b'{"jsonrpc":"2.0","method":"tools/list","params":null,"id":1}'),
        ("empty list", b'{"jsonrpc":"2.0","method":"tools/list","params":[],"id":1}'),
    ],
)
async def test_forwarded_post_injects_server_id_with_non_dict_params(monkeypatch, params_value, params_json):
    """Test internally-forwarded POST handles non-dict params (null, list) gracefully.

    Verifies that params is coerced to a dict and server_id is injected
    instead of crashing with TypeError and falling through to the SDK path.
    """
    # Third-Party
    import orjson

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            raise AssertionError("Should not fall through to SDK")

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.services.server_service.ServerService.entity_exists", AsyncMock(return_value=True))
    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    server_id = "abc-123-def-456"
    send, messages = _make_send_collector()
    scope = _make_scope(
        f"/servers/{server_id}/mcp",
        method="POST",
        headers=[(b"x-forwarded-internally", b"true")],
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'{"jsonrpc":"2.0","result":{"tools":[]},"id":1}'

    with patch("mcpgateway.transports.streamablehttp_transport.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        await wrapper.handle_streamable_http(scope, _make_receive(params_json), send)

        # Must reach /rpc (not fall through to SDK)
        mock_client.post.assert_called_once()
        posted_content = mock_client.post.call_args.kwargs["content"]
        posted_json = orjson.loads(posted_content)

        assert isinstance(posted_json["params"], dict), f"params should be dict, was {type(posted_json['params'])}"
        assert posted_json["params"]["server_id"] == server_id

    await wrapper.shutdown()
    assert messages[0]["status"] == 200


@pytest.mark.asyncio
async def test_forwarded_post_no_server_id_in_url_no_injection(monkeypatch):
    """Test internally-forwarded POST without server_id pattern in URL does not inject server_id.

    Verifies that requests to paths like /mcp (without /servers/{id}/) don't get
    server_id injection, ensuring the fix only applies to the correct URL pattern.
    """
    # Third-Party
    import orjson

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            raise AssertionError("Should not reach SDK")

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    original_body = b'{"jsonrpc":"2.0","method":"tools/list","params":{"other":"value"},"id":1}'
    scope = _make_scope(
        "/mcp",  # No /servers/{id}/ pattern
        method="POST",
        headers=[(b"x-forwarded-internally", b"true")],
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'{"jsonrpc":"2.0","result":{"tools":[]},"id":1}'

    with patch("mcpgateway.transports.streamablehttp_transport.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        await wrapper.handle_streamable_http(scope, _make_receive(original_body), send)

        # Verify the POST to /rpc does NOT include server_id
        mock_client.post.assert_called_once()
        posted_content = mock_client.post.call_args.kwargs["content"]
        posted_json = orjson.loads(posted_content)

        # Body should be unchanged - no server_id injection
        assert posted_json["params"] == {"other": "value"}
        assert "server_id" not in posted_json["params"]

    await wrapper.shutdown()
    assert messages[0]["status"] == 200


@pytest.mark.asyncio
async def test_forwarded_post_denies_non_owner_session_access(monkeypatch):
    """Internally forwarded requests must deny when session owner does not match requester."""

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            raise AssertionError("Should not reach SDK")

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._validate_streamable_session_access", AsyncMock(return_value=(False, 403, "Session access denied")))

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    body = b'{"jsonrpc":"2.0","method":"ping","id":"x1"}'
    scope = _make_scope("/mcp", method="POST", headers=[(b"x-forwarded-internally", b"true"), (b"mcp-session-id", b"sess-abc")])

    with patch("mcpgateway.transports.streamablehttp_transport.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        await wrapper.handle_streamable_http(scope, _make_receive(body), send)

        mock_client.post.assert_not_awaited()

    await wrapper.shutdown()
    assert messages[0]["status"] == 403


@pytest.mark.asyncio
async def test_forwarded_post_notification_no_server_id_injection(monkeypatch):
    """Test internally-forwarded notification does not inject server_id.

    Notifications return 202 early and should not go through server_id injection
    or routing to /rpc, even if the URL contains /servers/{id}/.
    """

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            raise AssertionError("Should not reach SDK")

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.services.server_service.ServerService.entity_exists", AsyncMock(return_value=True))
    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    server_id = "test-server-456"
    send, messages = _make_send_collector()
    body = b'{"jsonrpc":"2.0","method":"notifications/initialized"}'
    scope = _make_scope(
        f"/servers/{server_id}/mcp",
        method="POST",
        headers=[(b"x-forwarded-internally", b"true")],
    )

    # No httpx mock needed - should return 202 before any HTTP call
    await wrapper.handle_streamable_http(scope, _make_receive(body), send)

    await wrapper.shutdown()
    # Should return 202 Accepted for notification, not route to /rpc
    assert messages[0]["status"] == 202


@pytest.mark.asyncio
async def test_local_affinity_post_injects_server_id_regression(monkeypatch):
    """Test local-owner affinity POST still injects server_id (regression test).

    Verifies that the existing server_id injection for local-owner requests
    (lines 1565-1572) continues to work after the internally-forwarded fix.
    """
    # Third-Party
    import orjson

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            pass

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    monkeypatch.setattr("mcpgateway.services.server_service.ServerService.entity_exists", AsyncMock(return_value=True))
    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    server_id = "abc-def-123-456"  # Valid hex format
    original_body = orjson.dumps({"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 1})
    scope = _make_scope(f"/servers/{server_id}/mcp", method="POST", headers=[(b"mcp-session-id", b"sess-1")])
    receive = _make_receive(original_body)
    send, messages = _make_send_collector()

    mock_pool = MagicMock()
    mock_pool.get_streamable_http_session_owner = AsyncMock(return_value="worker-1")

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'{"jsonrpc":"2.0","result":{},"id":1}'

    with (
        patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
        patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "worker-1"),
        patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
        patch("mcpgateway.transports.streamablehttp_transport.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        await wrapper.handle_streamable_http(scope, receive, send)

        # Verify server_id was injected in local-owner branch
        mock_client.post.assert_called_once()
        posted_content = mock_client.post.call_args.kwargs["content"]
        posted_json = orjson.loads(posted_content)

        assert "params" in posted_json
        assert posted_json["params"]["server_id"] == server_id

    await wrapper.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params_value,params_json",
    [
        ("null", b'{"jsonrpc":"2.0","method":"tools/list","params":null,"id":1}'),
        ("empty list", b'{"jsonrpc":"2.0","method":"tools/list","params":[],"id":1}'),
    ],
)
async def test_local_affinity_post_injects_server_id_with_non_dict_params(monkeypatch, params_value, params_json):
    """Test local-owner affinity POST handles non-dict params (null, list) gracefully.

    Mirrors the forwarded-branch test to ensure parity between both injection paths.
    """
    # Third-Party
    import orjson

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            pass

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    monkeypatch.setattr("mcpgateway.services.server_service.ServerService.entity_exists", AsyncMock(return_value=True))
    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    server_id = "abc-def-123-456"
    scope = _make_scope(f"/servers/{server_id}/mcp", method="POST", headers=[(b"mcp-session-id", b"sess-1")])
    receive = _make_receive(params_json)
    send, messages = _make_send_collector()

    mock_pool = MagicMock()
    mock_pool.get_streamable_http_session_owner = AsyncMock(return_value="worker-1")

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'{"jsonrpc":"2.0","result":{},"id":1}'

    with (
        patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
        patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "worker-1"),
        patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
        patch("mcpgateway.transports.streamablehttp_transport.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        await wrapper.handle_streamable_http(scope, receive, send)

        mock_client.post.assert_called_once()
        posted_content = mock_client.post.call_args.kwargs["content"]
        posted_json = orjson.loads(posted_content)

        assert isinstance(posted_json["params"], dict), f"params should be dict, was {type(posted_json['params'])}"
        assert posted_json["params"]["server_id"] == server_id

    await wrapper.shutdown()


# ---------------------------------------------------------------------------
# Group 6: Session affinity owner forward (lines 1468-1523)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_affinity_forward_to_owner_worker(monkeypatch):
    """Test affinity forwards request to owner worker and returns response (lines 1478-1523)."""

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            raise AssertionError("Should not reach SDK")

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    scope = _make_scope("/mcp", method="POST", headers=[(b"mcp-session-id", b"sess-abc")])

    mock_pool = MagicMock()
    mock_pool.get_streamable_http_session_owner = AsyncMock(return_value="worker-2")
    mock_pool.forward_streamable_http_to_owner = AsyncMock(
        return_value={
            "status": 200,
            "headers": {"content-type": "application/json"},
            "body": b'{"jsonrpc":"2.0","result":{}}',
        }
    )

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    with (
        patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
        patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "worker-1"),
        patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
    ):
        await wrapper.handle_streamable_http(scope, _make_receive(b'{"jsonrpc":"2.0"}'), send)

    await wrapper.shutdown()
    assert messages[0]["status"] == 200


@pytest.mark.asyncio
async def test_affinity_forward_to_owner_worker_multipart_body(monkeypatch):
    """Cover multipart body read loop for affinity forwarding to another worker (lines 1483-1491)."""

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            raise AssertionError("Should not reach SDK")

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    scope = _make_scope("/mcp", method="POST", headers=[(b"mcp-session-id", b"sess-abc")])

    mock_pool = MagicMock()
    mock_pool.get_streamable_http_session_owner = AsyncMock(return_value="worker-2")
    mock_pool.forward_streamable_http_to_owner = AsyncMock(
        return_value={
            "status": 200,
            "headers": {"content-type": "application/json"},
            "body": b'{"jsonrpc":"2.0","result":{}}',
        }
    )

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    part1 = b'{"jsonrpc":"2.0","id":'
    part2 = b"1}"
    receive = _make_receive_sequence(
        [
            {"type": "http.unknown"},
            {"type": "http.request", "body": part1, "more_body": True},
            {"type": "http.request", "body": part2, "more_body": False},
        ]
    )

    with (
        patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
        patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "worker-1"),
        patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
    ):
        await wrapper.handle_streamable_http(scope, receive, send)

    await wrapper.shutdown()
    assert messages[0]["status"] == 200
    assert mock_pool.forward_streamable_http_to_owner.call_args.kwargs["body"] == part1 + part2


@pytest.mark.asyncio
async def test_affinity_forward_failure_falls_through(monkeypatch):
    """Test affinity forward failure falls through to local handling (line 1525-1527)."""

    sdk_called = False

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            nonlocal sdk_called
            sdk_called = True
            await send_func({"type": "http.response.start", "status": 200, "headers": []})
            await send_func({"type": "http.response.body", "body": b"sdk"})

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    scope = _make_scope("/mcp", method="POST", headers=[(b"mcp-session-id", b"sess-abc")])

    mock_pool = MagicMock()
    mock_pool.get_streamable_http_session_owner = AsyncMock(return_value="worker-2")
    mock_pool.forward_streamable_http_to_owner = AsyncMock(return_value=None)  # Forward failed

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    with (
        patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
        patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "worker-1"),
        patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
    ):
        await wrapper.handle_streamable_http(scope, _make_receive(b'{"jsonrpc":"2.0"}'), send)

    await wrapper.shutdown()
    assert sdk_called


@pytest.mark.asyncio
async def test_affinity_disconnect_during_body_read(monkeypatch):
    """Test affinity returns early when disconnect occurs during body read (line 1489-1490)."""

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            raise AssertionError("Should not reach SDK")

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    scope = _make_scope("/mcp", method="POST", headers=[(b"mcp-session-id", b"sess-abc")])

    mock_pool = MagicMock()
    mock_pool.get_streamable_http_session_owner = AsyncMock(return_value="worker-2")

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    with (
        patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
        patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "worker-1"),
        patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
    ):
        await wrapper.handle_streamable_http(scope, _make_receive_disconnect(), send)

    await wrapper.shutdown()
    assert messages == []  # No response - early return


@pytest.mark.asyncio
async def test_affinity_owner_is_self_non_post_falls_through_to_sdk(monkeypatch):
    """When owner is current worker but method is not POST, request should fall through to SDK (line 1529->1613)."""

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            await send_func({"type": "http.response.start", "status": 200, "headers": []})
            await send_func({"type": "http.response.body", "body": b"sdk"})

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    scope = _make_scope("/mcp", method="DELETE", headers=[(b"mcp-session-id", b"sess-abc")])

    mock_pool = MagicMock()
    mock_pool.get_streamable_http_session_owner = AsyncMock(return_value="worker-1")  # We own it, but not POST

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    with (
        patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
        patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "worker-1"),
        patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
    ):
        await wrapper.handle_streamable_http(scope, _make_receive(b""), send)

    await wrapper.shutdown()
    assert messages[0]["status"] == 200


# ---------------------------------------------------------------------------
# Group 7: Local affinity POST (lines 1529-1609)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_affinity_post_routes_to_rpc(monkeypatch):
    """Test local affinity POST routes to /rpc (lines 1529-1601)."""

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            raise AssertionError("Should not reach SDK")

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    body = b'{"jsonrpc":"2.0","method":"tools/list","id":1}'
    scope = _make_scope("/mcp", method="POST", headers=[(b"mcp-session-id", b"sess-abc")])

    mock_pool = MagicMock()
    mock_pool.get_streamable_http_session_owner = AsyncMock(return_value="worker-1")  # We own it

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'{"jsonrpc":"2.0","result":{}}'

    with (
        patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
        patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "worker-1"),
        patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
        patch("mcpgateway.transports.streamablehttp_transport.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        await wrapper.handle_streamable_http(scope, _make_receive(body), send)

    await wrapper.shutdown()
    assert messages[0]["status"] == 200


@pytest.mark.asyncio
async def test_local_affinity_post_denies_non_owner_session_access(monkeypatch):
    """Local affinity /rpc routing must deny cross-user stateful session replay."""

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            raise AssertionError("Should not reach SDK")

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._validate_streamable_session_access", AsyncMock(return_value=(False, 403, "Session access denied")))

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    body = b'{"jsonrpc":"2.0","method":"ping","id":"x2"}'
    scope = _make_scope("/mcp", method="POST", headers=[(b"mcp-session-id", b"sess-abc")])

    mock_pool = MagicMock()
    mock_pool.get_streamable_http_session_owner = AsyncMock(return_value="worker-1")

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    with (
        patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
        patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "worker-1"),
        patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
        patch("mcpgateway.transports.streamablehttp_transport.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        await wrapper.handle_streamable_http(scope, _make_receive(body), send)

        mock_client.post.assert_not_awaited()

    await wrapper.shutdown()
    assert messages[0]["status"] == 403


@pytest.mark.asyncio
async def test_local_affinity_post_routes_to_rpc_multipart_and_auth_header(monkeypatch):
    """Cover multipart body read + Authorization header copy for local affinity routing (lines 1536-1573)."""

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            raise AssertionError("Should not reach SDK")

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    scope = _make_scope(
        "/mcp",
        method="POST",
        headers=[
            (b"mcp-session-id", b"sess-abc"),
            (b"authorization", b"Bearer abc"),
        ],
    )

    mock_pool = MagicMock()
    mock_pool.get_streamable_http_session_owner = AsyncMock(return_value="worker-1")  # We own it

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'{"jsonrpc":"2.0","result":{}}'

    part1 = b'{"jsonrpc":"2.0","method":"tools/l'
    part2 = b'ist","id":1}'
    receive = _make_receive_sequence(
        [
            {"type": "http.unknown"},
            {"type": "http.request", "body": part1, "more_body": True},
            {"type": "http.request", "body": part2, "more_body": False},
        ]
    )

    with (
        patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
        patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "worker-1"),
        patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
        patch("mcpgateway.transports.streamablehttp_transport.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        await wrapper.handle_streamable_http(scope, receive, send)

    await wrapper.shutdown()
    assert messages[0]["status"] == 200
    assert mock_client.post.call_args.kwargs["headers"]["authorization"] == "Bearer abc"


@pytest.mark.asyncio
async def test_local_affinity_disconnect_during_body_read(monkeypatch):
    """Cover disconnect branch during local affinity body read (lines 1542-1543)."""

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            raise AssertionError("Should not reach SDK")

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    scope = _make_scope("/mcp", method="POST", headers=[(b"mcp-session-id", b"sess-abc")])

    mock_pool = MagicMock()
    mock_pool.get_streamable_http_session_owner = AsyncMock(return_value="worker-1")  # We own it

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    with (
        patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
        patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "worker-1"),
        patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
    ):
        await wrapper.handle_streamable_http(scope, _make_receive_disconnect(), send)

    await wrapper.shutdown()
    assert messages == []  # No response - early return


@pytest.mark.asyncio
async def test_local_affinity_post_empty_body_returns_202(monkeypatch):
    """Test local affinity POST with empty body returns 202 (line 1546-1550)."""

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            raise AssertionError("Should not reach SDK")

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    scope = _make_scope("/mcp", method="POST", headers=[(b"mcp-session-id", b"sess-abc")])

    mock_pool = MagicMock()
    mock_pool.get_streamable_http_session_owner = AsyncMock(return_value="worker-1")

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    with (
        patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
        patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "worker-1"),
        patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
    ):
        await wrapper.handle_streamable_http(scope, _make_receive(b""), send)

    await wrapper.shutdown()
    assert messages[0]["status"] == 202


@pytest.mark.asyncio
async def test_local_affinity_post_notification_returns_202(monkeypatch):
    """Test local affinity POST with notification returns 202 (line 1559-1563)."""

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            raise AssertionError("Should not reach SDK")

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    body = b'{"jsonrpc":"2.0","method":"notifications/initialized"}'
    scope = _make_scope("/mcp", method="POST", headers=[(b"mcp-session-id", b"sess-abc")])

    mock_pool = MagicMock()
    mock_pool.get_streamable_http_session_owner = AsyncMock(return_value="worker-1")

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    with (
        patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
        patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "worker-1"),
        patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
    ):
        await wrapper.handle_streamable_http(scope, _make_receive(body), send)

    await wrapper.shutdown()
    assert messages[0]["status"] == 202


@pytest.mark.asyncio
async def test_local_affinity_post_exception_falls_through(monkeypatch):
    """Test local affinity POST httpx exception falls through to SDK (line 1602-1604)."""

    sdk_called = False

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            nonlocal sdk_called
            sdk_called = True
            await send_func({"type": "http.response.start", "status": 200, "headers": []})
            await send_func({"type": "http.response.body", "body": b"sdk"})

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    body = b'{"jsonrpc":"2.0","method":"tools/list","id":1}'
    scope = _make_scope("/mcp", method="POST", headers=[(b"mcp-session-id", b"sess-abc")])

    mock_pool = MagicMock()
    mock_pool.get_streamable_http_session_owner = AsyncMock(return_value="worker-1")

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    with (
        patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
        patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "worker-1"),
        patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
        patch("mcpgateway.transports.streamablehttp_transport.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("httpx fail"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        await wrapper.handle_streamable_http(scope, _make_receive(body), send)

    await wrapper.shutdown()
    assert sdk_called


@pytest.mark.asyncio
async def test_local_affinity_runtime_error_falls_through(monkeypatch):
    """Test local affinity RuntimeError (pool not init) falls through (line 1606-1608)."""

    sdk_called = False

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            nonlocal sdk_called
            sdk_called = True
            await send_func({"type": "http.response.start", "status": 200, "headers": []})
            await send_func({"type": "http.response.body", "body": b"sdk"})

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    scope = _make_scope("/mcp", method="POST", headers=[(b"mcp-session-id", b"sess-abc")])

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    with (
        patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", side_effect=RuntimeError("not init")),
        patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
    ):
        await wrapper.handle_streamable_http(scope, _make_receive(b'{"jsonrpc":"2.0"}'), send)

    await wrapper.shutdown()
    assert sdk_called


@pytest.mark.asyncio
async def test_local_affinity_generic_exception_falls_through(monkeypatch):
    """Test local affinity generic Exception falls through (line 1609-1610)."""

    sdk_called = False

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            nonlocal sdk_called
            sdk_called = True
            await send_func({"type": "http.response.start", "status": 200, "headers": []})
            await send_func({"type": "http.response.body", "body": b"sdk"})

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    scope = _make_scope("/mcp", method="POST", headers=[(b"mcp-session-id", b"sess-abc")])

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    with (
        patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", side_effect=ValueError("generic err")),
        patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
    ):
        await wrapper.handle_streamable_http(scope, _make_receive(b'{"jsonrpc":"2.0"}'), send)

    await wrapper.shutdown()
    assert sdk_called


# ---------------------------------------------------------------------------
# Group 8: send_with_capture + registration (lines 1634-1673)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_with_capture_registers_session(monkeypatch):
    """Test send_with_capture captures session ID and registers ownership (lines 1634-1669)."""

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            # Simulate SDK returning a session ID in response headers
            await send_func(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"mcp-session-id", b"new-session-id")],
                }
            )
            await send_func({"type": "http.response.body", "body": b"ok"})

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    scope = _make_scope("/mcp", method="POST", headers=[])

    mock_pool = MagicMock()
    mock_pool.register_pool_session_owner = AsyncMock()

    with (
        patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
        patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "worker-1"),
    ):
        await wrapper.handle_streamable_http(scope, _make_receive(b""), send)

    await wrapper.shutdown()
    mock_pool.register_pool_session_owner.assert_called_once_with("new-session-id")


@pytest.mark.asyncio
async def test_send_with_capture_str_headers_and_non_matching_header(monkeypatch):
    """send_with_capture should handle str headers and skip non-matching names (lines 1636-1642)."""

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            # Header names/values provided as strings (not bytes) + a non-matching header first
            await send_func(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [("x-other", "1"), ("mcp-session-id", "new-session-id")],
                }
            )
            await send_func({"type": "http.response.body", "body": b"ok"})

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, _messages = _make_send_collector()
    scope = _make_scope("/mcp", method="POST", headers=[])

    mock_pool = MagicMock()
    mock_pool.register_pool_session_owner = AsyncMock()

    with (
        patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
        patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "worker-1"),
    ):
        await wrapper.handle_streamable_http(scope, _make_receive(b""), send)

    await wrapper.shutdown()
    mock_pool.register_pool_session_owner.assert_called_once_with("new-session-id")


@pytest.mark.asyncio
async def test_send_with_capture_registration_failure_logged(monkeypatch, caplog):
    """Test registration failure is logged but doesn't break request (lines 1667-1669)."""

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            await send_func(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"mcp-session-id", b"new-session-id")],
                }
            )
            await send_func({"type": "http.response.body", "body": b"ok"})

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    scope = _make_scope("/mcp", method="POST", headers=[])

    mock_pool = MagicMock()
    mock_pool.register_pool_session_owner = AsyncMock(side_effect=Exception("redis down"))

    with (
        patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
        patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "worker-1"),
        caplog.at_level("WARNING", logger="mcpgateway.transports.streamablehttp_transport"),
    ):
        await wrapper.handle_streamable_http(scope, _make_receive(b""), send)

    await wrapper.shutdown()
    assert "Failed to register session ownership" in caplog.text


@pytest.mark.asyncio
async def test_send_with_capture_no_session_id_no_registration(monkeypatch):
    """Test no registration when no session ID in response (lines 1656-1658)."""

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            # No mcp-session-id in response headers
            await send_func({"type": "http.response.start", "status": 200, "headers": []})
            await send_func({"type": "http.response.body", "body": b"ok"})

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    scope = _make_scope("/mcp", method="POST", headers=[])

    mock_pool = MagicMock()
    mock_pool.register_pool_session_owner = AsyncMock()

    with (
        patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
        patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "worker-1"),
    ):
        await wrapper.handle_streamable_http(scope, _make_receive(b""), send)

    await wrapper.shutdown()
    mock_pool.register_pool_session_owner.assert_not_called()


@pytest.mark.asyncio
async def test_send_with_capture_claims_owner_for_new_session(monkeypatch):
    """Captured server-emitted session IDs must be bound to the authenticated principal."""

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            await send_func(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"mcp-session-id", b"new-session-id")],
                }
            )
            await send_func({"type": "http.response.body", "body": b"ok"})

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._claim_streamable_session_owner", AsyncMock(return_value="dev@example.com"))

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, _messages = _make_send_collector()
    scope = _make_scope("/mcp", method="POST", headers=[])

    mock_pool = MagicMock()
    mock_pool.register_pool_session_owner = AsyncMock()

    with patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool):
        with patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "worker-1"):
            token = tr.user_context_var.set(
                {
                    "email": "dev@example.com",
                    "teams": ["team-1"],
                    "is_authenticated": True,
                    "is_admin": False,
                }
            )
            try:
                await wrapper.handle_streamable_http(scope, _make_receive(b""), send)
            finally:
                tr.user_context_var.reset(token)

    await wrapper.shutdown()
    tr._claim_streamable_session_owner.assert_awaited_once_with("new-session-id", "dev@example.com")
    mock_pool.register_pool_session_owner.assert_called_once_with("new-session-id")


@pytest.mark.asyncio
async def test_send_with_capture_does_not_register_denied_client_supplied_session(monkeypatch):
    """Client-supplied session IDs must not become owned when access is denied."""

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            await send_func({"type": "http.response.start", "status": 404, "headers": []})
            await send_func({"type": "http.response.body", "body": b"not found"})

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._validate_streamable_session_access", AsyncMock(return_value=(False, 404, "Session not found")))

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, _messages = _make_send_collector()
    scope = _make_scope("/mcp", method="POST", headers=[(b"mcp-session-id", b"attacker-sid")])

    mock_pool = MagicMock()
    mock_pool.register_pool_session_owner = AsyncMock()

    with (
        patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
        patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "worker-1"),
        patch("mcpgateway.services.mcp_session_pool.MCPSessionPool") as mock_session_class,
    ):
        mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)
        await wrapper.handle_streamable_http(scope, _make_receive(b'{"jsonrpc":"2.0","method":"ping","id":"x3"}'), send)

    await wrapper.shutdown()
    mock_pool.register_pool_session_owner.assert_not_called()


@pytest.mark.asyncio
async def test_handle_streamable_http_closed_resource_error_swallowed(monkeypatch):
    """ClosedResourceError from session manager should be swallowed as a normal disconnect (line 1673)."""
    # Third-Party
    import anyio

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            raise anyio.ClosedResourceError

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    # Keep affinity disabled for a minimal test that targets the exception handler.
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", False)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, messages = _make_send_collector()
    scope = _make_scope("/mcp", method="POST", headers=[])

    await wrapper.handle_streamable_http(scope, _make_receive(b""), send)
    await wrapper.shutdown()

    assert messages == []


# ---------------------------------------------------------------------------
# Group 9: Auth session token resolution (lines 1771-1780)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_session_token_admin_bypass(monkeypatch):
    """Test session token with is_admin gets teams=None (admin bypass) (line 1771-1772)."""

    async def fake_verify(token):
        return {
            "sub": "admin@example.com",
            "token_use": "session",
            "is_admin": True,
        }

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer session-tok")])
    sent = []

    async def send(msg):
        sent.append(msg)

    result = await streamable_http_auth(scope, None, send)
    assert result is True

    user_ctx = tr.user_context_var.get()
    assert user_ctx["teams"] is None  # Admin bypass
    assert user_ctx["is_admin"] is True


@pytest.mark.asyncio
async def test_auth_session_token_resolves_teams_from_db(monkeypatch):
    """Test session token resolves teams from DB for non-admin user (line 1773-1778)."""

    async def fake_verify(token):
        return {
            "sub": "user@example.com",
            "token_use": "session",
            "is_admin": False,
        }

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    mock_resolve = AsyncMock(return_value=["team-a", "team-b"])

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer session-tok")])
    sent = []

    async def send(msg):
        sent.append(msg)

    with (
        patch("mcpgateway.auth.resolve_session_teams", mock_resolve),
        patch("mcpgateway.cache.auth_cache.get_auth_cache") as mock_get_cache,
    ):
        mock_auth_cache = MagicMock()
        mock_auth_cache.get_team_membership_valid_sync.return_value = True
        mock_get_cache.return_value = mock_auth_cache
        result = await streamable_http_auth(scope, None, send)

    assert result is True
    user_ctx = tr.user_context_var.get()
    assert user_ctx["teams"] == ["team-a", "team-b"]
    expected_payload = {"sub": "user@example.com", "token_use": "session", "is_admin": False}
    mock_resolve.assert_called_once_with(expected_payload, "user@example.com", {"is_admin": False})


@pytest.mark.asyncio
async def test_auth_session_token_no_email_public_only(monkeypatch):
    """Test session token without email gets public-only access (line 1779-1780)."""

    async def fake_verify(token):
        return {
            "token_use": "session",
            "is_admin": False,
            # No sub, no email
        }

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer session-tok")])
    sent = []

    async def send(msg):
        sent.append(msg)

    result = await streamable_http_auth(scope, None, send)
    assert result is True

    user_ctx = tr.user_context_var.get()
    assert user_ctx["teams"] == []  # Public-only


@pytest.mark.asyncio
async def test_streamable_http_auth_verify_credentials_non_dict_payload(monkeypatch):
    """If verify_credentials returns a non-dict payload and no proxy user is present, auth should still pass (line 1867->1913)."""
    # Force standard JWT flow (no trusted proxy short-circuit)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_client_auth_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.trust_proxy_auth", False)

    async def fake_verify(token):
        return "ok"  # non-dict payload

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer good-token")])
    sent = []

    async def send(msg):
        sent.append(msg)

    assert await streamable_http_auth(scope, None, send) is True
    assert sent == []


@pytest.mark.asyncio
async def test_streamable_http_auth_rejects_revoked_jwt(monkeypatch):
    """Revoked JWTs should be rejected before user context is populated."""

    async def fake_verify(_token):
        return {
            "sub": "user@example.com",
            "jti": "revoked-jti",
            "teams": ["team-a"],
        }

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer token")])
    sent = []

    async def send(msg):
        sent.append(msg)

    with patch("mcpgateway.auth._check_token_revoked_sync", return_value=True):
        result = await streamable_http_auth(scope, None, send)

    assert result is False
    assert any(m.get("type") == "http.response.start" and m.get("status") == 401 for m in sent)


@pytest.mark.asyncio
async def test_streamable_http_auth_uses_cached_auth_context(monkeypatch):
    """Cached MCP auth context should bypass per-request revocation and user lookups."""

    # First-Party
    from mcpgateway.cache.auth_cache import auth_cache, CachedAuthContext

    async def fake_verify(_token):
        return {
            "sub": "cached@example.com",
            "jti": "cached-jti",
            "token_use": "api",
            "teams": [],
        }

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer token")])
    sent = []

    async def send(msg):
        sent.append(msg)

    with (
        patch.object(
            auth_cache,
            "get_auth_context",
            AsyncMock(
                return_value=CachedAuthContext(
                    user={
                        "email": "cached@example.com",
                        "is_admin": False,
                        "is_active": True,
                    },
                    personal_team_id=None,
                    is_token_revoked=False,
                )
            ),
        ),
        patch("mcpgateway.auth._check_token_revoked_sync", side_effect=AssertionError("should not be called")),
        patch("mcpgateway.auth._get_user_by_email_sync", side_effect=AssertionError("should not be called")),
    ):
        result = await streamable_http_auth(scope, None, send)

    assert result is True
    assert sent == []
    assert tr.user_context_var.get()["email"] == "cached@example.com"


@pytest.mark.asyncio
async def test_streamable_http_auth_rejects_revoked_cached_auth_context(monkeypatch):
    """Cached revoked auth context should reject before touching the DB helpers."""

    # First-Party
    from mcpgateway.cache.auth_cache import auth_cache, CachedAuthContext

    async def fake_verify(_token):
        return {
            "sub": "cached@example.com",
            "jti": "cached-jti",
            "token_use": "api",
            "teams": [],
        }

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer token")])
    sent = []

    async def send(msg):
        sent.append(msg)

    with (
        patch.object(
            auth_cache,
            "get_auth_context",
            AsyncMock(
                return_value=CachedAuthContext(
                    user={
                        "email": "cached@example.com",
                        "is_admin": False,
                        "is_active": True,
                    },
                    personal_team_id=None,
                    is_token_revoked=True,
                )
            ),
        ),
        patch("mcpgateway.auth._check_token_revoked_sync", side_effect=AssertionError("should not be called")),
        patch("mcpgateway.auth._get_user_by_email_sync", side_effect=AssertionError("should not be called")),
    ):
        result = await streamable_http_auth(scope, None, send)

    assert result is False
    assert any(m.get("type") == "http.response.start" and m.get("status") == 401 for m in sent)


@pytest.mark.asyncio
async def test_streamable_http_auth_rejects_inactive_cached_auth_context(monkeypatch):
    """Cached inactive auth context should reject before touching the DB helpers."""

    # First-Party
    from mcpgateway.cache.auth_cache import auth_cache, CachedAuthContext

    async def fake_verify(_token):
        return {
            "sub": "cached@example.com",
            "jti": "cached-jti",
            "token_use": "api",
            "teams": [],
        }

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer token")])
    sent = []

    async def send(msg):
        sent.append(msg)

    with (
        patch.object(
            auth_cache,
            "get_auth_context",
            AsyncMock(
                return_value=CachedAuthContext(
                    user={
                        "email": "cached@example.com",
                        "is_admin": False,
                        "is_active": False,
                    },
                    personal_team_id=None,
                    is_token_revoked=False,
                )
            ),
        ),
        patch("mcpgateway.auth._check_token_revoked_sync", side_effect=AssertionError("should not be called")),
        patch("mcpgateway.auth._get_user_by_email_sync", side_effect=AssertionError("should not be called")),
    ):
        result = await streamable_http_auth(scope, None, send)

    assert result is False
    assert any(m.get("type") == "http.response.start" and m.get("status") == 401 for m in sent)


@pytest.mark.asyncio
async def test_streamable_http_auth_uses_batched_auth_context(monkeypatch):
    """MCP auth should use the existing batched auth lookup before per-query fallbacks."""

    # First-Party
    from mcpgateway.cache.auth_cache import auth_cache

    async def fake_verify(_token):
        return {
            "sub": "batched@example.com",
            "jti": "batched-jti",
            "token_use": "api",
            "teams": [],
        }

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer token")])
    sent = []

    async def send(msg):
        sent.append(msg)

    with (
        patch.object(auth_cache, "get_auth_context", AsyncMock(return_value=None)),
        patch.object(auth_cache, "set_auth_context", AsyncMock()) as mock_set_auth_context,
        patch(
            "mcpgateway.auth._get_auth_context_batched_sync",
            return_value={
                "user": {
                    "email": "batched@example.com",
                    "is_admin": False,
                    "is_active": True,
                },
                "personal_team_id": None,
                "is_token_revoked": False,
                "team_ids": [],
            },
        ),
        patch("mcpgateway.auth._check_token_revoked_sync", side_effect=AssertionError("should not be called")),
        patch("mcpgateway.auth._get_user_by_email_sync", side_effect=AssertionError("should not be called")),
    ):
        result = await streamable_http_auth(scope, None, send)

    assert result is True
    assert sent == []
    mock_set_auth_context.assert_awaited_once()
    assert tr.user_context_var.get()["email"] == "batched@example.com"


@pytest.mark.asyncio
async def test_streamable_http_auth_rejects_revoked_batched_auth_context(monkeypatch):
    """Batched MCP auth lookup should reject revoked tokens before individual DB fallbacks."""

    # First-Party
    from mcpgateway.cache.auth_cache import auth_cache

    async def fake_verify(_token):
        return {
            "sub": "batched@example.com",
            "jti": "batched-jti",
            "token_use": "api",
            "teams": [],
        }

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer token")])
    sent = []

    async def send(msg):
        sent.append(msg)

    with (
        patch.object(auth_cache, "get_auth_context", AsyncMock(return_value=None)),
        patch(
            "mcpgateway.auth._get_auth_context_batched_sync",
            return_value={
                "user": {
                    "email": "batched@example.com",
                    "is_admin": False,
                    "is_active": True,
                },
                "personal_team_id": None,
                "is_token_revoked": True,
                "team_ids": [],
            },
        ),
        patch("mcpgateway.auth._check_token_revoked_sync", side_effect=AssertionError("should not be called")),
        patch("mcpgateway.auth._get_user_by_email_sync", side_effect=AssertionError("should not be called")),
    ):
        result = await streamable_http_auth(scope, None, send)

    assert result is False
    assert any(m.get("type") == "http.response.start" and m.get("status") == 401 for m in sent)


@pytest.mark.asyncio
async def test_streamable_http_auth_rejects_inactive_batched_auth_context(monkeypatch):
    """Batched MCP auth lookup should reject inactive users before individual DB fallbacks."""

    # First-Party
    from mcpgateway.cache.auth_cache import auth_cache

    async def fake_verify(_token):
        return {
            "sub": "batched@example.com",
            "jti": "batched-jti",
            "token_use": "api",
            "teams": [],
        }

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer token")])
    sent = []

    async def send(msg):
        sent.append(msg)

    with (
        patch.object(auth_cache, "get_auth_context", AsyncMock(return_value=None)),
        patch(
            "mcpgateway.auth._get_auth_context_batched_sync",
            return_value={
                "user": {
                    "email": "batched@example.com",
                    "is_admin": False,
                    "is_active": False,
                },
                "personal_team_id": None,
                "is_token_revoked": False,
                "team_ids": [],
            },
        ),
        patch("mcpgateway.auth._check_token_revoked_sync", side_effect=AssertionError("should not be called")),
        patch("mcpgateway.auth._get_user_by_email_sync", side_effect=AssertionError("should not be called")),
    ):
        result = await streamable_http_auth(scope, None, send)

    assert result is False
    assert any(m.get("type") == "http.response.start" and m.get("status") == 401 for m in sent)


@pytest.mark.asyncio
async def test_streamable_http_auth_rejects_inactive_user(monkeypatch):
    """Inactive users should be rejected after JWT validation."""

    async def fake_verify(_token):
        return {
            "sub": "disabled@example.com",
            "jti": "active-jti",
            "teams": ["team-a"],
        }

    disabled_user = MagicMock()
    disabled_user.is_active = False

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer token")])
    sent = []

    async def send(msg):
        sent.append(msg)

    with (
        patch("mcpgateway.auth._check_token_revoked_sync", return_value=False),
        patch("mcpgateway.auth._get_user_by_email_sync", return_value=disabled_user),
    ):
        result = await streamable_http_auth(scope, None, send)

    assert result is False
    assert any(m.get("type") == "http.response.start" and m.get("status") == 401 for m in sent)


@pytest.mark.asyncio
async def test_streamable_http_auth_revocation_check_exception_fails_open(monkeypatch):
    """Revocation-check backend failures should fail open and allow the request."""

    async def fake_verify(_token):
        return {
            "sub": "user@example.com",
            "jti": "jti-1",
            # Keep public-only to avoid team-membership DB checks; this test targets
            # revocation-check failure behavior only.
            "teams": [],
        }

    active_user = MagicMock()
    active_user.is_active = True

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer token")])
    sent = []

    async def send(msg):
        sent.append(msg)

    with (
        patch("mcpgateway.auth._check_token_revoked_sync", side_effect=RuntimeError("db unavailable")),
        patch("mcpgateway.auth._get_user_by_email_sync", return_value=active_user),
    ):
        result = await streamable_http_auth(scope, None, send)

    assert result is True
    assert sent == []


@pytest.mark.asyncio
async def test_streamable_http_auth_rejects_missing_user_when_required(monkeypatch):
    """When require_user_in_db is enabled, unknown users should be rejected."""

    async def fake_verify(_token):
        return {
            "sub": "missing@example.com",
            "jti": "ok-jti",
            "teams": ["team-a"],
        }

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.require_user_in_db", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.platform_admin_email", "admin@example.com")

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer token")])
    sent = []

    async def send(msg):
        sent.append(msg)

    with (
        patch("mcpgateway.auth._check_token_revoked_sync", return_value=False),
        patch("mcpgateway.auth._get_user_by_email_sync", return_value=None),
    ):
        result = await streamable_http_auth(scope, None, send)

    assert result is False
    assert any(m.get("type") == "http.response.start" and m.get("status") == 401 for m in sent)
    assert any(m.get("type") == "http.response.body" and b"User not found in database" in m.get("body", b"") for m in sent)


# ---------------------------------------------------------------------------
# Proxy function tests - comprehensive coverage for direct_proxy mode
# ---------------------------------------------------------------------------


class TestProxyFunctions:
    """Test suite for proxy functions (_proxy_list_tools_to_gateway, _proxy_list_resources_to_gateway, _proxy_read_resource_to_gateway)."""

    @pytest.mark.asyncio
    async def test_proxy_list_tools_success(self):
        """Test successful proxy of list_tools to remote gateway."""
        # Mock gateway
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-123"
        mock_gateway.url = "http://remote-gateway.example.com/mcp"
        mock_gateway.passthrough_headers = None
        mock_gateway.auth_type = "bearer"
        mock_gateway.auth_token = "remote-token"

        # Mock MCP SDK response
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.description = "Test tool"
        mock_tool.inputSchema = {"type": "object"}

        mock_result = MagicMock()
        mock_result.tools = [mock_tool]

        # Mock streamablehttp_client and ClientSession
        mock_session = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        @asynccontextmanager
        async def mock_client(*args, **kwargs):
            yield (None, None, lambda: "session-id")

        with patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", mock_client):
            with patch("mcpgateway.transports.streamablehttp_transport.ClientSession", return_value=mock_session):
                with patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={"Authorization": "Bearer remote-token"}):
                    result = await tr._proxy_list_tools_to_gateway(mock_gateway, {}, {}, None)

        assert len(result) == 1
        assert result[0].name == "test_tool"
        mock_session.list_tools.assert_called_once()

    @pytest.mark.asyncio
    async def test_proxy_list_tools_with_meta(self):
        """Test proxy list_tools forwards _meta to remote gateway."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-123"
        mock_gateway.url = "http://remote-gateway.example.com/mcp"
        mock_gateway.passthrough_headers = None

        mock_result = MagicMock()
        mock_result.tools = []

        mock_session = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        @asynccontextmanager
        async def mock_client(*args, **kwargs):
            yield (None, None, lambda: "session-id")

        meta_data = {"request_id": "req-123"}

        with patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", mock_client):
            with patch("mcpgateway.transports.streamablehttp_transport.ClientSession", return_value=mock_session):
                with patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}):
                    await tr._proxy_list_tools_to_gateway(mock_gateway, {}, {}, meta_data)

        # Verify list_tools was called with params
        call_args = mock_session.list_tools.call_args
        assert call_args is not None
        params = call_args.kwargs.get("params")
        assert params is not None
        # PaginatedRequestParams stores _meta internally, verify it was created
        assert hasattr(params, "model_dump") or hasattr(params, "_meta")

    @pytest.mark.asyncio
    async def test_proxy_list_tools_with_passthrough_headers(self):
        """Test proxy list_tools forwards passthrough headers via compute_passthrough_headers_cached."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-123"
        mock_gateway.url = "http://remote-gateway.example.com/mcp"
        mock_gateway.passthrough_headers = ["X-Custom-Header", "X-Request-ID"]
        mock_gateway.auth_type = "bearer"

        request_headers = {
            "x-custom-header": "custom-value",
            "x-request-id": "req-456",
            "x-ignored": "ignored-value",
        }

        mock_result = MagicMock()
        mock_result.tools = []

        mock_session = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        captured_headers = {}

        @asynccontextmanager
        async def mock_client(*args, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            yield (None, None, lambda: "session-id")

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", mock_client):
            with patch("mcpgateway.transports.streamablehttp_transport.ClientSession", return_value=mock_session):
                with patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}):
                    with patch("mcpgateway.transports.streamablehttp_transport.SessionLocal", return_value=mock_db):
                        with patch("mcpgateway.transports.streamablehttp_transport.global_config_cache") as mock_cache:
                            mock_cache.get_passthrough_headers.return_value = ["X-Custom-Header", "X-Request-ID"]
                            with patch("mcpgateway.transports.streamablehttp_transport.settings") as mock_settings:
                                mock_settings.default_passthrough_headers = []
                                mock_settings.mcpgateway_direct_proxy_timeout = 30
                                with patch("mcpgateway.utils.passthrough_headers.settings") as mock_ph_settings:
                                    mock_ph_settings.enable_header_passthrough = True
                                    mock_ph_settings.enable_overwrite_base_headers = False
                                    await tr._proxy_list_tools_to_gateway(mock_gateway, request_headers, {}, None)

        # Verify compute_passthrough_headers_cached forwarded the headers
        assert "X-Custom-Header" in captured_headers
        assert captured_headers["X-Custom-Header"] == "custom-value"
        assert "X-Request-ID" in captured_headers
        assert captured_headers["X-Request-ID"] == "req-456"

    @pytest.mark.asyncio
    async def test_proxy_list_tools_exception_returns_empty(self):
        """Test proxy list_tools returns empty list on exception."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-123"
        mock_gateway.url = "http://remote-gateway.example.com/mcp"
        mock_gateway.passthrough_headers = None

        with patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", side_effect=Exception("Connection failed")):
            with patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}):
                result = await tr._proxy_list_tools_to_gateway(mock_gateway, {}, {}, None)

        assert result == []

    @pytest.mark.asyncio
    async def test_proxy_list_resources_success(self):
        """Test successful proxy of list_resources to remote gateway."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-456"
        mock_gateway.url = "http://remote-gateway.example.com/mcp"
        mock_gateway.passthrough_headers = None

        mock_resource = MagicMock()
        mock_resource.uri = "file:///test.txt"
        mock_resource.name = "test.txt"
        mock_resource.description = "Test file"
        mock_resource.mimeType = "text/plain"

        mock_result = MagicMock()
        mock_result.resources = [mock_resource]

        mock_session = AsyncMock()
        mock_session.list_resources = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        @asynccontextmanager
        async def mock_client(*args, **kwargs):
            yield (None, None, lambda: "session-id")

        with patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", mock_client):
            with patch("mcpgateway.transports.streamablehttp_transport.ClientSession", return_value=mock_session):
                with patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}):
                    result = await tr._proxy_list_resources_to_gateway(mock_gateway, {}, {}, None)

        assert len(result) == 1
        assert result[0].uri == "file:///test.txt"
        mock_session.list_resources.assert_called_once()

    @pytest.mark.asyncio
    async def test_proxy_list_resources_with_passthrough_headers(self):
        """Test proxy list_resources forwards passthrough headers via compute_passthrough_headers_cached."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-456"
        mock_gateway.url = "http://remote-gateway.example.com/mcp"
        mock_gateway.passthrough_headers = ["X-Tenant-ID", "X-Request-ID"]
        mock_gateway.auth_type = "bearer"

        request_headers = {
            "x-tenant-id": "tenant-abc",
            "x-request-id": "req-789",
            "x-ignored": "ignored-value",
        }

        mock_result = MagicMock()
        mock_result.resources = []

        mock_session = AsyncMock()
        mock_session.list_resources = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        captured_headers = {}

        @asynccontextmanager
        async def mock_client(*args, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            yield (None, None, lambda: "session-id")

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", mock_client):
            with patch("mcpgateway.transports.streamablehttp_transport.ClientSession", return_value=mock_session):
                with patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}):
                    with patch("mcpgateway.transports.streamablehttp_transport.SessionLocal", return_value=mock_db):
                        with patch("mcpgateway.transports.streamablehttp_transport.global_config_cache") as mock_cache:
                            mock_cache.get_passthrough_headers.return_value = ["X-Tenant-ID", "X-Request-ID"]
                            with patch("mcpgateway.transports.streamablehttp_transport.settings") as mock_settings:
                                mock_settings.default_passthrough_headers = []
                                mock_settings.mcpgateway_direct_proxy_timeout = 30
                                with patch("mcpgateway.utils.passthrough_headers.settings") as mock_ph_settings:
                                    mock_ph_settings.enable_header_passthrough = True
                                    mock_ph_settings.enable_overwrite_base_headers = False
                                    await tr._proxy_list_resources_to_gateway(mock_gateway, request_headers, {}, None)

        # Verify compute_passthrough_headers_cached forwarded the headers
        assert "X-Tenant-ID" in captured_headers
        assert captured_headers["X-Tenant-ID"] == "tenant-abc"
        assert "X-Request-ID" in captured_headers
        assert captured_headers["X-Request-ID"] == "req-789"

    @pytest.mark.asyncio
    async def test_proxy_list_resources_with_meta(self):
        """Test proxy list_resources forwards _meta to remote gateway."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-456"
        mock_gateway.url = "http://remote-gateway.example.com/mcp"
        mock_gateway.passthrough_headers = None

        mock_result = MagicMock()
        mock_result.resources = []

        mock_session = AsyncMock()
        mock_session.list_resources = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        @asynccontextmanager
        async def mock_client(*args, **kwargs):
            yield (None, None, lambda: "session-id")

        meta_data = {"trace_id": "trace-789"}

        with patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", mock_client):
            with patch("mcpgateway.transports.streamablehttp_transport.ClientSession", return_value=mock_session):
                with patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}):
                    await tr._proxy_list_resources_to_gateway(mock_gateway, {}, {}, meta_data)

        call_args = mock_session.list_resources.call_args
        assert call_args is not None
        params = call_args.kwargs.get("params")
        assert params is not None
        # PaginatedRequestParams stores _meta as 'meta' attribute
        assert hasattr(params, "meta")
        assert params.meta.trace_id == meta_data["trace_id"]

    @pytest.mark.asyncio
    async def test_proxy_list_resources_exception_returns_empty(self):
        """Test proxy list_resources returns empty list on exception."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-456"
        mock_gateway.url = "http://remote-gateway.example.com/mcp"
        mock_gateway.passthrough_headers = None

        with patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", side_effect=Exception("Network error")):
            with patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}):
                result = await tr._proxy_list_resources_to_gateway(mock_gateway, {}, {}, None)

        assert result == []

    @pytest.mark.asyncio
    async def test_proxy_read_resource_success_text(self):
        """Test successful proxy of read_resource returning text content."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-789"
        mock_gateway.url = "http://remote-gateway.example.com/mcp"
        mock_gateway.passthrough_headers = None

        mock_content = MagicMock()
        mock_content.text = "File content here"

        mock_result = MagicMock()
        mock_result.contents = [mock_content]

        mock_session = AsyncMock()
        mock_session.read_resource = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        @asynccontextmanager
        async def mock_client(*args, **kwargs):
            yield (None, None, lambda: "session-id")

        # Mock request_headers_var
        tr.request_headers_var.set({})

        with patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", mock_client):
            with patch("mcpgateway.transports.streamablehttp_transport.ClientSession", return_value=mock_session):
                with patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}):
                    result = await tr._proxy_read_resource_to_gateway(mock_gateway, "file:///test.txt", {}, None)

        assert len(result) == 1
        assert result[0].text == "File content here"
        mock_session.read_resource.assert_called_once()

    @pytest.mark.asyncio
    async def test_proxy_read_resource_with_meta(self):
        """Test proxy read_resource forwards _meta using send_request."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-789"
        mock_gateway.url = "http://remote-gateway.example.com/mcp"
        mock_gateway.passthrough_headers = None

        mock_content = MagicMock()
        mock_content.text = "Content"

        mock_result = MagicMock()
        mock_result.contents = [mock_content]

        mock_session = AsyncMock()
        mock_session.send_request = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        @asynccontextmanager
        async def mock_client(*args, **kwargs):
            yield (None, None, lambda: "session-id")

        meta_data = {"correlation_id": "corr-999"}
        tr.request_headers_var.set({})

        with patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", mock_client):
            with patch("mcpgateway.transports.streamablehttp_transport.ClientSession", return_value=mock_session):
                with patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}):
                    result = await tr._proxy_read_resource_to_gateway(mock_gateway, "file:///test.txt", {}, meta_data)

        assert len(result) == 1
        # Verify send_request was called (not read_resource)
        mock_session.send_request.assert_called_once()
        mock_session.read_resource.assert_not_called()

    @pytest.mark.asyncio
    async def test_proxy_read_resource_forwards_gateway_id_header(self):
        """Test proxy read_resource forwards X-Context-Forge-Gateway-Id header."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-789"
        mock_gateway.url = "http://remote-gateway.example.com/mcp"
        mock_gateway.passthrough_headers = None

        mock_result = MagicMock()
        mock_result.contents = []

        mock_session = AsyncMock()
        mock_session.read_resource = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        @asynccontextmanager
        async def mock_client(*args, **kwargs):
            headers = kwargs.get("headers", {})
            # Verify X-Context-Forge-Gateway-Id is forwarded
            assert "X-Context-Forge-Gateway-Id" in headers
            assert headers["X-Context-Forge-Gateway-Id"] == "original-gw-id"
            yield (None, None, lambda: "session-id")

        # Set request headers with gateway ID
        tr.request_headers_var.set({"x-context-forge-gateway-id": "original-gw-id"})

        with patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", mock_client):
            with patch("mcpgateway.transports.streamablehttp_transport.ClientSession", return_value=mock_session):
                with patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}):
                    await tr._proxy_read_resource_to_gateway(mock_gateway, "file:///test.txt", {}, None)

    @pytest.mark.asyncio
    async def test_proxy_read_resource_with_passthrough_headers(self):
        """Test proxy read_resource forwards passthrough headers via compute_passthrough_headers_cached."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-789"
        mock_gateway.url = "http://remote-gateway.example.com/mcp"
        mock_gateway.passthrough_headers = ["X-Tenant-ID"]
        mock_gateway.auth_type = "bearer"

        mock_result = MagicMock()
        mock_result.contents = []

        mock_session = AsyncMock()
        mock_session.read_resource = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        captured_headers = {}

        @asynccontextmanager
        async def mock_client(*args, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            yield (None, None, lambda: "session-id")

        tr.request_headers_var.set({"x-tenant-id": "tenant-123"})

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", mock_client):
            with patch("mcpgateway.transports.streamablehttp_transport.ClientSession", return_value=mock_session):
                with patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}):
                    with patch("mcpgateway.transports.streamablehttp_transport.SessionLocal", return_value=mock_db):
                        with patch("mcpgateway.transports.streamablehttp_transport.global_config_cache") as mock_cache:
                            mock_cache.get_passthrough_headers.return_value = ["X-Tenant-ID"]
                            with patch("mcpgateway.transports.streamablehttp_transport.settings") as mock_settings:
                                mock_settings.default_passthrough_headers = []
                                mock_settings.mcpgateway_direct_proxy_timeout = 30
                                with patch("mcpgateway.utils.passthrough_headers.settings") as mock_ph_settings:
                                    mock_ph_settings.enable_header_passthrough = True
                                    mock_ph_settings.enable_overwrite_base_headers = False
                                    await tr._proxy_read_resource_to_gateway(mock_gateway, "file:///test.txt", {}, None)

        # Verify compute_passthrough_headers_cached forwarded the headers
        assert "X-Tenant-ID" in captured_headers
        assert captured_headers["X-Tenant-ID"] == "tenant-123"

    @pytest.mark.asyncio
    async def test_proxy_read_resource_exception_returns_empty(self):
        """Test proxy read_resource returns empty list on exception."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-789"
        mock_gateway.url = "http://remote-gateway.example.com/mcp"
        mock_gateway.passthrough_headers = None

        tr.request_headers_var.set({})

        with patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", side_effect=Exception("Timeout")):
            with patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}):
                result = await tr._proxy_read_resource_to_gateway(mock_gateway, "file:///test.txt", {}, None)

        assert result == []


# ---------------------------------------------------------------------------
# X-Upstream-Authorization rename tests for direct proxy paths (Issue #3643)
# ---------------------------------------------------------------------------


class TestProxyUpstreamAuthorizationRename:
    """Verify that X-Upstream-Authorization is renamed to Authorization in all direct proxy functions.

    Before the fix for #3643, the direct proxy functions used a manual header loop that
    skipped the X-Upstream-Authorization → Authorization rename. These tests ensure the
    rename happens correctly via compute_passthrough_headers_cached.
    """

    def _make_gateway(self, auth_type="bearer", passthrough_headers=None):
        gw = MagicMock()
        gw.id = "gw-upstream"
        gw.url = "http://remote.example.com/mcp"
        gw.auth_type = auth_type
        gw.passthrough_headers = passthrough_headers
        return gw

    def _make_mocks(self, result_attr="tools", result_value=None):
        mock_result = MagicMock()
        setattr(mock_result, result_attr, result_value or [])
        mock_session = AsyncMock()
        if result_attr == "tools":
            mock_session.list_tools = AsyncMock(return_value=mock_result)
        elif result_attr == "resources":
            mock_session.list_resources = AsyncMock(return_value=mock_result)
        else:
            mock_session.read_resource = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        return mock_session

    @pytest.mark.asyncio
    async def test_list_tools_renames_upstream_auth(self):
        """X-Upstream-Authorization is renamed to Authorization for tools/list."""
        gw = self._make_gateway()
        session = self._make_mocks("tools")
        request_headers = {"x-upstream-authorization": "Bearer upstream-token-123"}
        captured = {}

        @asynccontextmanager
        async def mock_client(*args, **kwargs):
            captured.update(kwargs.get("headers", {}))
            yield (None, None, lambda: "session-id")

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", mock_client):
            with patch("mcpgateway.transports.streamablehttp_transport.ClientSession", return_value=session):
                with patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}):
                    with patch("mcpgateway.transports.streamablehttp_transport.SessionLocal", return_value=mock_db):
                        with patch("mcpgateway.transports.streamablehttp_transport.global_config_cache") as mock_cache:
                            mock_cache.get_passthrough_headers.return_value = []
                            with patch("mcpgateway.transports.streamablehttp_transport.settings") as mock_settings:
                                mock_settings.default_passthrough_headers = []
                                mock_settings.mcpgateway_direct_proxy_timeout = 30
                                with patch("mcpgateway.utils.passthrough_headers.settings") as mock_ph_settings:
                                    mock_ph_settings.enable_header_passthrough = False
                                    mock_ph_settings.enable_overwrite_base_headers = False
                                    await tr._proxy_list_tools_to_gateway(gw, request_headers, {}, None)

        assert "Authorization" in captured, "X-Upstream-Authorization was not renamed to Authorization"
        assert captured["Authorization"] == "Bearer upstream-token-123"

    @pytest.mark.asyncio
    async def test_list_resources_renames_upstream_auth(self):
        """X-Upstream-Authorization is renamed to Authorization for resources/list."""
        gw = self._make_gateway()
        session = self._make_mocks("resources")
        request_headers = {"x-upstream-authorization": "Bearer upstream-token-456"}
        captured = {}

        @asynccontextmanager
        async def mock_client(*args, **kwargs):
            captured.update(kwargs.get("headers", {}))
            yield (None, None, lambda: "session-id")

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", mock_client):
            with patch("mcpgateway.transports.streamablehttp_transport.ClientSession", return_value=session):
                with patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}):
                    with patch("mcpgateway.transports.streamablehttp_transport.SessionLocal", return_value=mock_db):
                        with patch("mcpgateway.transports.streamablehttp_transport.global_config_cache") as mock_cache:
                            mock_cache.get_passthrough_headers.return_value = []
                            with patch("mcpgateway.transports.streamablehttp_transport.settings") as mock_settings:
                                mock_settings.default_passthrough_headers = []
                                mock_settings.mcpgateway_direct_proxy_timeout = 30
                                with patch("mcpgateway.utils.passthrough_headers.settings") as mock_ph_settings:
                                    mock_ph_settings.enable_header_passthrough = False
                                    mock_ph_settings.enable_overwrite_base_headers = False
                                    await tr._proxy_list_resources_to_gateway(gw, request_headers, {}, None)

        assert "Authorization" in captured, "X-Upstream-Authorization was not renamed to Authorization"
        assert captured["Authorization"] == "Bearer upstream-token-456"

    @pytest.mark.asyncio
    async def test_read_resource_renames_upstream_auth(self):
        """X-Upstream-Authorization is renamed to Authorization for resources/read."""
        gw = self._make_gateway()
        session = self._make_mocks("contents")
        captured = {}

        @asynccontextmanager
        async def mock_client(*args, **kwargs):
            captured.update(kwargs.get("headers", {}))
            yield (None, None, lambda: "session-id")

        tr.request_headers_var.set({"x-upstream-authorization": "Bearer upstream-token-789"})

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", mock_client):
            with patch("mcpgateway.transports.streamablehttp_transport.ClientSession", return_value=session):
                with patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}):
                    with patch("mcpgateway.transports.streamablehttp_transport.SessionLocal", return_value=mock_db):
                        with patch("mcpgateway.transports.streamablehttp_transport.global_config_cache") as mock_cache:
                            mock_cache.get_passthrough_headers.return_value = []
                            with patch("mcpgateway.transports.streamablehttp_transport.settings") as mock_settings:
                                mock_settings.default_passthrough_headers = []
                                mock_settings.mcpgateway_direct_proxy_timeout = 30
                                with patch("mcpgateway.utils.passthrough_headers.settings") as mock_ph_settings:
                                    mock_ph_settings.enable_header_passthrough = False
                                    mock_ph_settings.enable_overwrite_base_headers = False
                                    await tr._proxy_read_resource_to_gateway(gw, "file:///test.txt", {}, None)

        assert "Authorization" in captured, "X-Upstream-Authorization was not renamed to Authorization"
        assert captured["Authorization"] == "Bearer upstream-token-789"

    @pytest.mark.asyncio
    async def test_list_tools_no_upstream_auth_no_authorization_added(self):
        """When no X-Upstream-Authorization is sent, no Authorization header should be injected."""
        gw = self._make_gateway()
        session = self._make_mocks("tools")
        request_headers = {"x-request-id": "req-100"}
        captured = {}

        @asynccontextmanager
        async def mock_client(*args, **kwargs):
            captured.update(kwargs.get("headers", {}))
            yield (None, None, lambda: "session-id")

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", mock_client):
            with patch("mcpgateway.transports.streamablehttp_transport.ClientSession", return_value=session):
                with patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}):
                    with patch("mcpgateway.transports.streamablehttp_transport.SessionLocal", return_value=mock_db):
                        with patch("mcpgateway.transports.streamablehttp_transport.global_config_cache") as mock_cache:
                            mock_cache.get_passthrough_headers.return_value = []
                            with patch("mcpgateway.transports.streamablehttp_transport.settings") as mock_settings:
                                mock_settings.default_passthrough_headers = []
                                mock_settings.mcpgateway_direct_proxy_timeout = 30
                                with patch("mcpgateway.utils.passthrough_headers.settings") as mock_ph_settings:
                                    mock_ph_settings.enable_header_passthrough = False
                                    mock_ph_settings.enable_overwrite_base_headers = False
                                    await tr._proxy_list_tools_to_gateway(gw, request_headers, {}, None)

        assert "Authorization" not in captured

    @pytest.mark.asyncio
    async def test_upstream_auth_works_even_when_passthrough_disabled(self):
        """X-Upstream-Authorization rename works even when ENABLE_HEADER_PASSTHROUGH=false."""
        gw = self._make_gateway()
        session = self._make_mocks("tools")
        request_headers = {"x-upstream-authorization": "Bearer token-even-disabled"}
        captured = {}

        @asynccontextmanager
        async def mock_client(*args, **kwargs):
            captured.update(kwargs.get("headers", {}))
            yield (None, None, lambda: "session-id")

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", mock_client):
            with patch("mcpgateway.transports.streamablehttp_transport.ClientSession", return_value=session):
                with patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}):
                    with patch("mcpgateway.transports.streamablehttp_transport.SessionLocal", return_value=mock_db):
                        with patch("mcpgateway.transports.streamablehttp_transport.global_config_cache") as mock_cache:
                            mock_cache.get_passthrough_headers.return_value = []
                            with patch("mcpgateway.transports.streamablehttp_transport.settings") as mock_settings:
                                mock_settings.default_passthrough_headers = []
                                mock_settings.mcpgateway_direct_proxy_timeout = 30
                                with patch("mcpgateway.utils.passthrough_headers.settings") as mock_ph_settings:
                                    mock_ph_settings.enable_header_passthrough = False  # Explicitly disabled
                                    mock_ph_settings.enable_overwrite_base_headers = False
                                    await tr._proxy_list_tools_to_gateway(gw, request_headers, {}, None)

        # X-Upstream-Authorization rename is always enabled regardless of feature flag
        assert "Authorization" in captured
        assert captured["Authorization"] == "Bearer token-even-disabled"

    @pytest.mark.asyncio
    async def test_empty_passthrough_headers_does_not_fall_through_to_global(self):
        """When gateway.passthrough_headers=[] (explicit empty), no global headers should leak through."""
        gw = self._make_gateway(passthrough_headers=[])  # Explicitly empty
        session = self._make_mocks("tools")
        request_headers = {"x-tenant-id": "tenant-secret", "x-upstream-authorization": "Bearer upstream-tok"}
        captured = {}

        @asynccontextmanager
        async def mock_client(*args, **kwargs):
            captured.update(kwargs.get("headers", {}))
            yield (None, None, lambda: "session-id")

        with patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", mock_client):
            with patch("mcpgateway.transports.streamablehttp_transport.ClientSession", return_value=session):
                with patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}):
                    with patch("mcpgateway.transports.streamablehttp_transport.settings") as mock_settings:
                        mock_settings.default_passthrough_headers = ["X-Tenant-Id"]
                        mock_settings.mcpgateway_direct_proxy_timeout = 30
                        with patch("mcpgateway.utils.passthrough_headers.settings") as mock_ph_settings:
                            mock_ph_settings.enable_header_passthrough = True
                            mock_ph_settings.enable_overwrite_base_headers = False
                            await tr._proxy_list_tools_to_gateway(gw, request_headers, {}, None)

        # X-Upstream-Authorization rename still works (always enabled)
        assert "Authorization" in captured
        assert captured["Authorization"] == "Bearer upstream-tok"
        # But X-Tenant-Id from the global allowlist must NOT leak through
        assert "X-Tenant-Id" not in captured

    @pytest.mark.asyncio
    async def test_db_failure_still_proxies_with_gateway_passthrough_headers(self):
        """When gateway has explicit passthrough_headers, DB failure should not break the proxy."""
        gw = self._make_gateway(passthrough_headers=["X-Tenant-Id"])
        session = self._make_mocks("tools")
        request_headers = {"x-tenant-id": "tenant-value"}
        captured = {}

        @asynccontextmanager
        async def mock_client(*args, **kwargs):
            captured.update(kwargs.get("headers", {}))
            yield (None, None, lambda: "session-id")

        # Do NOT mock SessionLocal — if the code correctly skips the DB lookup
        # when gateway.passthrough_headers is not None, SessionLocal is never called.
        # If it IS called, an unmocked SessionLocal will raise, caught by the outer
        # except, and the proxy returns []. We detect that via the captured headers.
        with patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", mock_client):
            with patch("mcpgateway.transports.streamablehttp_transport.ClientSession", return_value=session):
                with patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}):
                    with patch("mcpgateway.transports.streamablehttp_transport.SessionLocal", side_effect=RuntimeError("DB is down")):
                        with patch("mcpgateway.transports.streamablehttp_transport.settings") as mock_settings:
                            mock_settings.default_passthrough_headers = []
                            mock_settings.mcpgateway_direct_proxy_timeout = 30
                            with patch("mcpgateway.utils.passthrough_headers.settings") as mock_ph_settings:
                                mock_ph_settings.enable_header_passthrough = True
                                mock_ph_settings.enable_overwrite_base_headers = False
                                await tr._proxy_list_tools_to_gateway(gw, request_headers, {}, None)

        # Should succeed because gateway has explicit passthrough_headers — no DB needed
        assert "X-Tenant-Id" in captured
        assert captured["X-Tenant-Id"] == "tenant-value"


# ---------------------------------------------------------------------------
# Direct proxy mode integration tests for list_tools, list_resources, read_resource
# ---------------------------------------------------------------------------


class TestDirectProxyMode:
    """Test direct_proxy mode in list_tools, list_resources, and read_resource handlers."""

    @pytest.fixture(autouse=True)
    def enable_direct_proxy(self):
        """Enable direct_proxy feature flag for all tests in this class."""
        with patch.object(tr.settings, "mcpgateway_direct_proxy_enabled", True):
            yield

    @pytest.mark.asyncio
    async def test_list_tools_direct_proxy_mode_success(self):
        """Test list_tools uses direct_proxy when gateway mode is direct_proxy."""
        # Setup
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-direct"
        mock_gateway.gateway_mode = "direct_proxy"
        mock_gateway.url = "http://remote.example.com/mcp"

        mock_db = MagicMock()
        mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway)))

        @asynccontextmanager
        async def mock_get_db():
            yield mock_db

        # Mock proxy function
        mock_tools = [MagicMock(name="proxied_tool")]

        # Set context vars
        tr.server_id_var.set("server-123")
        tr.request_headers_var.set({"x-context-forge-gateway-id": "gw-direct"})
        tr.user_context_var.set({"email": "user@example.com", "teams": ["team1"], "is_authenticated": True})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            with patch("mcpgateway.transports.streamablehttp_transport.check_gateway_access", return_value=True):
                with patch("mcpgateway.transports.streamablehttp_transport._proxy_list_tools_to_gateway", return_value=mock_tools):
                    result = await tr.list_tools()

        assert result == mock_tools

    @pytest.mark.asyncio
    async def test_list_tools_direct_proxy_access_denied(self):
        """Test list_tools returns empty when gateway access is denied."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-direct"
        mock_gateway.gateway_mode = "direct_proxy"

        mock_db = MagicMock()
        mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway)))

        @asynccontextmanager
        async def mock_get_db():
            yield mock_db

        tr.server_id_var.set("server-123")
        tr.request_headers_var.set({"x-context-forge-gateway-id": "gw-direct"})
        tr.user_context_var.set({"email": "user@example.com", "teams": ["team1"], "is_authenticated": True})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            with patch("mcpgateway.transports.streamablehttp_transport.check_gateway_access", return_value=False):
                result = await tr.list_tools()

        assert result == []

    @pytest.mark.asyncio
    async def test_list_tools_gateway_not_found_logs_warning(self):
        """Test list_tools logs warning when gateway not found and returns empty."""
        mock_db = MagicMock()
        mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

        @asynccontextmanager
        async def mock_get_db():
            yield mock_db

        tr.server_id_var.set("server-123")
        tr.request_headers_var.set({"x-context-forge-gateway-id": "gw-missing"})
        tr.user_context_var.set({"email": "user@example.com", "teams": [], "is_authenticated": True})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            result = await tr.list_tools()

        # Gateway not found logs warning and returns empty (server also not found)
        assert result == []

    @pytest.mark.asyncio
    async def test_list_tools_gateway_not_direct_proxy_mode_logs_debug(self):
        """Test list_tools logs debug when gateway is not in direct_proxy mode."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-cache"
        mock_gateway.gateway_mode = "cache"  # Not direct_proxy

        mock_db = MagicMock()
        mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway)))

        @asynccontextmanager
        async def mock_get_db():
            yield mock_db

        tr.server_id_var.set("server-123")
        tr.request_headers_var.set({"x-context-forge-gateway-id": "gw-cache"})
        tr.user_context_var.set({"email": "user@example.com", "teams": [], "is_authenticated": True})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            result = await tr.list_tools()

        # Gateway not in direct_proxy mode logs debug and returns empty (server also not found)
        assert result == []

    @pytest.mark.asyncio
    async def test_list_resources_direct_proxy_mode_success(self):
        """Test list_resources uses direct_proxy when gateway mode is direct_proxy."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-direct"
        mock_gateway.gateway_mode = "direct_proxy"

        mock_db = MagicMock()
        mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway)))

        @asynccontextmanager
        async def mock_get_db():
            yield mock_db

        mock_resources = [MagicMock(uri="file:///proxied.txt")]

        tr.server_id_var.set("server-123")
        tr.request_headers_var.set({"x-context-forge-gateway-id": "gw-direct"})
        tr.user_context_var.set({"email": "user@example.com", "teams": ["team1"], "is_authenticated": True})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            with patch("mcpgateway.transports.streamablehttp_transport.check_gateway_access", return_value=True):
                with patch("mcpgateway.transports.streamablehttp_transport._proxy_list_resources_to_gateway", return_value=mock_resources):
                    result = await tr.list_resources()

        assert result == mock_resources

    @pytest.mark.asyncio
    async def test_list_resources_direct_proxy_access_denied(self):
        """Test list_resources returns empty when gateway access is denied."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-direct"
        mock_gateway.gateway_mode = "direct_proxy"

        mock_db = MagicMock()
        mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway)))

        @asynccontextmanager
        async def mock_get_db():
            yield mock_db

        tr.server_id_var.set("server-123")
        tr.request_headers_var.set({"x-context-forge-gateway-id": "gw-direct"})
        tr.user_context_var.set({"email": "user@example.com", "teams": ["team1"], "is_authenticated": True})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            with patch("mcpgateway.transports.streamablehttp_transport.check_gateway_access", return_value=False):
                result = await tr.list_resources()

        assert result == []

    @pytest.mark.asyncio
    async def test_read_resource_direct_proxy_mode_success_text(self):
        """Test read_resource uses direct_proxy and returns text content."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-direct"
        mock_gateway.gateway_mode = "direct_proxy"

        mock_db = MagicMock()
        mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway)))

        @asynccontextmanager
        async def mock_get_db():
            yield mock_db

        mock_content = MagicMock()
        mock_content.text = "Proxied content"
        mock_content.blob = None

        tr.server_id_var.set("server-123")
        tr.request_headers_var.set({"x-context-forge-gateway-id": "gw-direct"})
        tr.user_context_var.set({"email": "user@example.com", "teams": ["team1"], "is_authenticated": True})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            with patch("mcpgateway.transports.streamablehttp_transport.check_gateway_access", return_value=True):
                with patch("mcpgateway.transports.streamablehttp_transport._proxy_read_resource_to_gateway", return_value=[mock_content]):
                    result = await tr.read_resource("file:///test.txt")

        assert result == "Proxied content"

    @pytest.mark.asyncio
    async def test_read_resource_direct_proxy_mode_success_blob(self):
        """Test read_resource uses direct_proxy and returns blob content."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-direct"
        mock_gateway.gateway_mode = "direct_proxy"

        mock_db = MagicMock()
        mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway)))

        @asynccontextmanager
        async def mock_get_db():
            yield mock_db

        # Create a mock that only has blob attribute (no text attribute)
        class MockContent:
            blob = b"Binary data"

        mock_content = MockContent()

        tr.server_id_var.set("server-123")
        tr.request_headers_var.set({"x-context-forge-gateway-id": "gw-direct"})
        tr.user_context_var.set({"email": "user@example.com", "teams": ["team1"], "is_authenticated": True})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            with patch("mcpgateway.transports.streamablehttp_transport.check_gateway_access", return_value=True):
                with patch("mcpgateway.transports.streamablehttp_transport._proxy_read_resource_to_gateway", return_value=[mock_content]):
                    result = await tr.read_resource("file:///binary.dat")

        assert result == b"Binary data"

    @pytest.mark.asyncio
    async def test_read_resource_direct_proxy_access_denied_returns_empty(self):
        """Test read_resource returns empty string when gateway access is denied."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-direct"
        mock_gateway.gateway_mode = "direct_proxy"

        mock_db = MagicMock()
        mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway)))

        @asynccontextmanager
        async def mock_get_db():
            yield mock_db

        tr.server_id_var.set("server-123")
        tr.request_headers_var.set({"x-context-forge-gateway-id": "gw-direct"})
        tr.user_context_var.set({"email": "user@example.com", "teams": ["team1"], "is_authenticated": True})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            with patch("mcpgateway.transports.streamablehttp_transport.check_gateway_access", return_value=False):
                result = await tr.read_resource("file:///test.txt")

        # Access denied returns empty string directly (no exception raised)
        assert result == ""

    @pytest.mark.asyncio
    async def test_read_resource_direct_proxy_empty_contents_returns_empty_string(self):
        """Test read_resource returns empty string when proxy returns no contents."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-direct"
        mock_gateway.gateway_mode = "direct_proxy"

        mock_db = MagicMock()
        mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway)))

        @asynccontextmanager
        async def mock_get_db():
            yield mock_db

        tr.server_id_var.set("server-123")
        tr.request_headers_var.set({"x-context-forge-gateway-id": "gw-direct"})
        tr.user_context_var.set({"email": "user@example.com", "teams": ["team1"], "is_authenticated": True})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            with patch("mcpgateway.transports.streamablehttp_transport.check_gateway_access", return_value=True):
                with patch("mcpgateway.transports.streamablehttp_transport._proxy_read_resource_to_gateway", return_value=[]):
                    result = await tr.read_resource("file:///empty.txt")

        assert result == ""

    @pytest.mark.asyncio
    async def test_list_tools_direct_proxy_with_meta_extraction(self):
        """Test list_tools extracts _meta from request context in direct_proxy mode."""
        # Standard
        from unittest.mock import PropertyMock

        mock_gateway = MagicMock()
        mock_gateway.id = "gw-direct"
        mock_gateway.gateway_mode = "direct_proxy"

        mock_db = MagicMock()
        mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway)))

        @asynccontextmanager
        async def mock_get_db():
            yield mock_db

        mock_meta = MagicMock()
        mock_request_ctx = MagicMock()
        mock_request_ctx.meta = mock_meta

        mock_tools = [MagicMock(name="proxied_tool")]

        tr.server_id_var.set("server-123")
        tr.request_headers_var.set({"x-context-forge-gateway-id": "gw-direct"})
        tr.user_context_var.set({"email": "user@example.com", "teams": ["team1"], "is_authenticated": True})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            with patch("mcpgateway.transports.streamablehttp_transport.check_gateway_access", return_value=True):
                with patch("mcpgateway.transports.streamablehttp_transport._proxy_list_tools_to_gateway", return_value=mock_tools) as mock_proxy:
                    with patch.object(type(tr.mcp_app), "request_context", new_callable=PropertyMock, return_value=mock_request_ctx):
                        result = await tr.list_tools()

        assert result == mock_tools
        # Verify meta was forwarded to proxy function
        mock_proxy.assert_awaited_once()
        assert mock_proxy.call_args[0][3] == mock_meta

    @pytest.mark.asyncio
    async def test_list_resources_direct_proxy_with_meta_extraction(self):
        """Test list_resources extracts _meta from request context in direct_proxy mode."""
        # Standard
        from unittest.mock import PropertyMock

        mock_gateway = MagicMock()
        mock_gateway.id = "gw-direct"
        mock_gateway.gateway_mode = "direct_proxy"

        mock_db = MagicMock()
        mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway)))

        @asynccontextmanager
        async def mock_get_db():
            yield mock_db

        mock_meta = MagicMock()
        mock_request_ctx = MagicMock()
        mock_request_ctx.meta = mock_meta

        mock_resources = [MagicMock(uri="file:///proxied.txt")]

        tr.server_id_var.set("server-123")
        tr.request_headers_var.set({"x-context-forge-gateway-id": "gw-direct"})
        tr.user_context_var.set({"email": "user@example.com", "teams": ["team1"], "is_authenticated": True})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            with patch("mcpgateway.transports.streamablehttp_transport.check_gateway_access", return_value=True):
                with patch("mcpgateway.transports.streamablehttp_transport._proxy_list_resources_to_gateway", return_value=mock_resources) as mock_proxy:
                    with patch.object(type(tr.mcp_app), "request_context", new_callable=PropertyMock, return_value=mock_request_ctx):
                        result = await tr.list_resources()

        assert result == mock_resources
        mock_proxy.assert_awaited_once()
        assert mock_proxy.call_args[0][3] == mock_meta

    @pytest.mark.asyncio
    async def test_list_resources_gateway_not_direct_proxy_mode(self):
        """Test list_resources falls through when gateway is not in direct_proxy mode."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-cache"
        mock_gateway.gateway_mode = "cache"

        mock_db = MagicMock()
        mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway)))

        @asynccontextmanager
        async def mock_get_db():
            yield mock_db

        tr.server_id_var.set("server-123")
        tr.request_headers_var.set({"x-context-forge-gateway-id": "gw-cache"})
        tr.user_context_var.set({"email": "user@example.com", "teams": [], "is_authenticated": True})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            result = await tr.list_resources()

        assert result == []

    @pytest.mark.asyncio
    async def test_list_resources_gateway_not_found(self):
        """Test list_resources logs warning when gateway not found and falls through."""
        mock_db = MagicMock()
        mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

        @asynccontextmanager
        async def mock_get_db():
            yield mock_db

        tr.server_id_var.set("server-123")
        tr.request_headers_var.set({"x-context-forge-gateway-id": "gw-missing"})
        tr.user_context_var.set({"email": "user@example.com", "teams": [], "is_authenticated": True})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            result = await tr.list_resources()

        assert result == []

    @pytest.mark.asyncio
    async def test_read_resource_direct_proxy_with_meta_extraction(self):
        """Test read_resource extracts _meta from request context in direct_proxy mode."""
        # Standard
        from unittest.mock import PropertyMock

        mock_gateway = MagicMock()
        mock_gateway.id = "gw-direct"
        mock_gateway.gateway_mode = "direct_proxy"

        mock_db = MagicMock()
        mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway)))

        @asynccontextmanager
        async def mock_get_db():
            yield mock_db

        mock_meta = MagicMock()
        mock_meta.model_dump.return_value = {"trace_id": "test-meta"}
        mock_request_ctx = MagicMock()
        mock_request_ctx.meta = mock_meta

        mock_content = MagicMock()
        mock_content.text = "Proxied content with meta"

        tr.server_id_var.set("server-123")
        tr.request_headers_var.set({"x-context-forge-gateway-id": "gw-direct"})
        tr.user_context_var.set({"email": "user@example.com", "teams": ["team1"], "is_authenticated": True})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            with patch("mcpgateway.transports.streamablehttp_transport.check_gateway_access", return_value=True):
                with patch("mcpgateway.transports.streamablehttp_transport._proxy_read_resource_to_gateway", return_value=[mock_content]) as mock_proxy:
                    with patch.object(type(tr.mcp_app), "request_context", new_callable=PropertyMock, return_value=mock_request_ctx):
                        result = await tr.read_resource("file:///meta.txt")

        assert result == "Proxied content with meta"
        mock_proxy.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_read_resource_gateway_not_direct_proxy_mode(self):
        """Test read_resource falls through when gateway is not in direct_proxy mode."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-cache"
        mock_gateway.gateway_mode = "cache"

        mock_db = MagicMock()
        mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway)))

        @asynccontextmanager
        async def mock_get_db():
            yield mock_db

        tr.server_id_var.set("server-123")
        tr.request_headers_var.set({"x-context-forge-gateway-id": "gw-cache"})
        tr.user_context_var.set({"email": "user@example.com", "teams": [], "is_authenticated": True})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            with patch("mcpgateway.transports.streamablehttp_transport.resource_service") as mock_rs:
                mock_rs.read_resource = AsyncMock(return_value=MagicMock(blob=None, text="cached"))
                result = await tr.read_resource("file:///test.txt")

        assert result == "cached"

    @pytest.mark.asyncio
    async def test_read_resource_gateway_not_found(self):
        """Test read_resource logs warning when gateway not found and falls through."""
        mock_db = MagicMock()
        mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

        @asynccontextmanager
        async def mock_get_db():
            yield mock_db

        tr.server_id_var.set("server-123")
        tr.request_headers_var.set({"x-context-forge-gateway-id": "gw-missing"})
        tr.user_context_var.set({"email": "user@example.com", "teams": [], "is_authenticated": True})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            with patch("mcpgateway.transports.streamablehttp_transport.resource_service") as mock_rs:
                mock_rs.read_resource = AsyncMock(return_value=MagicMock(blob=None, text="from-cache"))
                result = await tr.read_resource("file:///test.txt")

        assert result == "from-cache"


# ---------------------------------------------------------------------------
# call_tool direct_proxy tests
# ---------------------------------------------------------------------------


class TestCallToolDirectProxy:
    """Test direct_proxy mode in the call_tool handler."""

    @pytest.fixture(autouse=True)
    def enable_direct_proxy(self):
        """Enable direct_proxy feature flag for all tests in this class."""
        with patch.object(tr.settings, "mcpgateway_direct_proxy_enabled", True):
            yield

    @pytest.mark.asyncio
    async def test_call_tool_direct_proxy_success(self):
        """Test call_tool returns CallToolResult from invoke_tool_direct when
        gateway header is present, gateway is direct_proxy, and access is granted."""
        # Third-Party
        from mcp import types as mcp_types

        mock_gateway = MagicMock()
        mock_gateway.id = "gw-direct"
        mock_gateway.gateway_mode = "direct_proxy"

        mock_db = MagicMock()
        mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway)))

        @asynccontextmanager
        async def mock_get_db():
            yield mock_db

        expected_result = mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="direct proxy result")],
            isError=False,
        )

        mock_invoke_direct = AsyncMock(return_value=expected_result)

        # Set context vars
        tr.server_id_var.set("server-123")
        tr.request_headers_var.set({"x-context-forge-gateway-id": "gw-direct"})
        tr.user_context_var.set({"email": "user@test.com", "teams": ["team1"], "is_admin": False, "is_authenticated": True})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            with patch("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", return_value="gw-direct"):
                with patch("mcpgateway.transports.streamablehttp_transport._check_scoped_permission", return_value=True):
                    with patch("mcpgateway.transports.streamablehttp_transport._check_streamable_permission", new_callable=AsyncMock, return_value=True):
                        with patch("mcpgateway.transports.streamablehttp_transport.check_gateway_access", new_callable=AsyncMock, return_value=True):
                            with patch.object(tr.tool_service, "invoke_tool_direct", mock_invoke_direct):
                                result = await tr.call_tool("my_tool", {"arg": "value"})

        assert isinstance(result, mcp_types.CallToolResult)
        assert result.isError is False
        assert result.content[0].text == "direct proxy result"
        mock_invoke_direct.assert_awaited_once()
        call_kwargs = mock_invoke_direct.call_args
        assert call_kwargs.kwargs["gateway_id"] == "gw-direct"
        assert call_kwargs.kwargs["name"] == "my_tool"
        assert call_kwargs.kwargs["arguments"] == {"arg": "value"}

    @pytest.mark.asyncio
    async def test_call_tool_direct_proxy_access_denied(self):
        """Test call_tool returns isError=True with 'Tool not found' when access is denied."""
        # Third-Party
        from mcp import types as mcp_types

        mock_gateway = MagicMock()
        mock_gateway.id = "gw-direct"
        mock_gateway.gateway_mode = "direct_proxy"

        mock_db = MagicMock()
        mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway)))

        @asynccontextmanager
        async def mock_get_db():
            yield mock_db

        tr.server_id_var.set("server-123")
        tr.request_headers_var.set({"x-context-forge-gateway-id": "gw-direct"})
        tr.user_context_var.set({"email": "user@test.com", "teams": ["team1"], "is_admin": False, "is_authenticated": True})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            with patch("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", return_value="gw-direct"):
                with patch("mcpgateway.transports.streamablehttp_transport._check_scoped_permission", return_value=True):
                    with patch("mcpgateway.transports.streamablehttp_transport._check_streamable_permission", new_callable=AsyncMock, return_value=True):
                        with patch("mcpgateway.transports.streamablehttp_transport.check_gateway_access", new_callable=AsyncMock, return_value=False):
                            result = await tr.call_tool("secret_tool", {"arg": "value"})

        assert isinstance(result, mcp_types.CallToolResult)
        assert result.isError is True
        assert len(result.content) == 1
        assert result.content[0].text == "Tool not found: secret_tool"

    @pytest.mark.asyncio
    async def test_call_tool_direct_proxy_exception_returns_error(self):
        """Test call_tool returns error when invoke_tool_direct raises (no fallback to cache mode)."""
        # Third-Party
        from mcp import types as mcp_types

        mock_gateway = MagicMock()
        mock_gateway.id = "gw-direct"
        mock_gateway.gateway_mode = "direct_proxy"

        mock_db = MagicMock()
        mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway)))

        @asynccontextmanager
        async def mock_get_db():
            yield mock_db

        # invoke_tool_direct raises an exception
        mock_invoke_direct = AsyncMock(side_effect=RuntimeError("connection failed"))

        tr.server_id_var.set("server-123")
        tr.request_headers_var.set({"x-context-forge-gateway-id": "gw-direct"})
        tr.user_context_var.set({"email": "user@test.com", "teams": ["team1"], "is_admin": False, "is_authenticated": True})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            with patch("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", return_value="gw-direct"):
                with patch("mcpgateway.transports.streamablehttp_transport._check_scoped_permission", return_value=True):
                    with patch("mcpgateway.transports.streamablehttp_transport._check_streamable_permission", new_callable=AsyncMock, return_value=True):
                        with patch("mcpgateway.transports.streamablehttp_transport.check_gateway_access", new_callable=AsyncMock, return_value=True):
                            with patch.object(tr.tool_service, "invoke_tool_direct", mock_invoke_direct):
                                result = await tr.call_tool("my_tool", {"arg": "value"})

        # invoke_tool_direct was called and raised
        mock_invoke_direct.assert_awaited_once()
        # Should return error result, NOT fall through to normal mode
        assert isinstance(result, mcp_types.CallToolResult)
        assert result.isError is True
        assert result.content[0].text == "Direct proxy tool invocation failed"

    @pytest.mark.asyncio
    async def test_call_tool_direct_proxy_gateway_not_direct_proxy_falls_through(self):
        """Test call_tool falls through to normal mode when gateway is not in direct_proxy mode."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-cache"
        mock_gateway.gateway_mode = "cache"  # Not direct_proxy

        mock_db = MagicMock()
        mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway)))

        @asynccontextmanager
        async def mock_get_db():
            yield mock_db

        # Normal mode invoke_tool returns a result with content
        mock_content_item = MagicMock(spec=[])
        mock_content_item.type = "text"
        mock_content_item.text = "normal result"
        mock_content_item.annotations = None
        mock_content_item.meta = None
        mock_content_item.size = None
        normal_result = MagicMock(spec=[])
        normal_result.content = [mock_content_item]
        normal_result.structuredContent = None
        mock_invoke_normal = AsyncMock(return_value=normal_result)

        tr.server_id_var.set("server-123")
        tr.request_headers_var.set({"x-context-forge-gateway-id": "gw-cache"})
        tr.user_context_var.set({"email": "user@test.com", "teams": ["team1"], "is_admin": False, "is_authenticated": True})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            with patch("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", return_value="gw-cache"):
                with patch("mcpgateway.transports.streamablehttp_transport._check_scoped_permission", return_value=True):
                    with patch("mcpgateway.transports.streamablehttp_transport._check_streamable_permission", new_callable=AsyncMock, return_value=True):
                        with patch.object(tr.tool_service, "invoke_tool", mock_invoke_normal):
                            with patch("mcpgateway.transports.streamablehttp_transport.settings") as mock_settings:
                                mock_settings.mcpgateway_session_affinity_enabled = False
                                await tr.call_tool("my_tool", {"arg": "value"})

        # Normal mode invoke_tool was called since gateway is not direct_proxy
        mock_invoke_normal.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_call_tool_direct_proxy_feature_disabled_falls_through(self):
        """Test call_tool falls through to normal mode when feature flag is disabled."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-direct"
        mock_gateway.gateway_mode = "direct_proxy"

        mock_db = MagicMock()
        mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway)))

        @asynccontextmanager
        async def mock_get_db():
            yield mock_db

        mock_content_item = MagicMock(spec=[])
        mock_content_item.type = "text"
        mock_content_item.text = "cache result"
        mock_content_item.annotations = None
        mock_content_item.meta = None
        mock_content_item.size = None
        normal_result = MagicMock(spec=[])
        normal_result.content = [mock_content_item]
        normal_result.structuredContent = None
        mock_invoke_normal = AsyncMock(return_value=normal_result)
        mock_invoke_direct = AsyncMock()

        tr.server_id_var.set("server-123")
        tr.request_headers_var.set({"x-context-forge-gateway-id": "gw-direct"})
        tr.user_context_var.set({"email": "user@test.com", "teams": ["team1"], "is_admin": False, "is_authenticated": True})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            with patch("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", return_value="gw-direct"):
                with patch("mcpgateway.transports.streamablehttp_transport._check_scoped_permission", return_value=True):
                    with patch("mcpgateway.transports.streamablehttp_transport._check_streamable_permission", new_callable=AsyncMock, return_value=True):
                        with patch.object(tr.tool_service, "invoke_tool_direct", mock_invoke_direct):
                            with patch.object(tr.tool_service, "invoke_tool", mock_invoke_normal):
                                with patch("mcpgateway.transports.streamablehttp_transport.settings") as mock_settings:
                                    mock_settings.mcpgateway_direct_proxy_enabled = False
                                    mock_settings.mcpgateway_session_affinity_enabled = False
                                    await tr.call_tool("my_tool", {"arg": "value"})

        # Direct proxy was NOT called since feature flag is disabled
        mock_invoke_direct.assert_not_awaited()
        # Normal mode was used instead
        mock_invoke_normal.assert_awaited_once()


# ---------------------------------------------------------------------------
# list_resources & direct proxy edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_resources_gateway_found_not_direct_proxy_mode(monkeypatch):
    """Test list_resources when gateway is found but not in direct_proxy mode."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_resources, request_headers_var, server_id_var, user_context_var

    mock_gateway = MagicMock()
    mock_gateway.id = "gw-cache"
    mock_gateway.gateway_mode = "cache"

    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway)))

    @asynccontextmanager
    async def mock_get_db():
        yield mock_db

    # Set authenticated user context to bypass OAuth enforcement
    user_token = user_context_var.set({"is_authenticated": True, "sub": "test@example.com"})
    server_token = server_id_var.set("server-123")
    headers_token = request_headers_var.set({"x-context-forge-gateway-id": "gw-cache"})

    with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
        with patch("mcpgateway.transports.streamablehttp_transport.resource_service") as mock_rs:
            mock_rs.list_server_resources = AsyncMock(return_value=[])

            # This triggers the "Gateway found but not in direct_proxy mode" log path
            await list_resources()

            # Should fall back to cache mode
            mock_rs.list_server_resources.assert_called_once()

    server_id_var.reset(server_token)
    request_headers_var.reset(headers_token)
    user_context_var.reset(user_token)


@pytest.mark.asyncio
async def test_list_resources_direct_proxy_disabled_setting(monkeypatch):
    """Test list_resources when gateway is direct_proxy but setting is disabled."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_resources, request_headers_var, server_id_var

    mock_gateway = MagicMock()
    mock_gateway.id = "gw-direct"
    mock_gateway.gateway_mode = "direct_proxy"

    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway)))

    @asynccontextmanager
    async def mock_get_db():
        yield mock_db

    server_token = server_id_var.set("server-123")
    headers_token = request_headers_var.set({"x-context-forge-gateway-id": "gw-direct"})

    with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
        with patch("mcpgateway.transports.streamablehttp_transport.settings") as mock_settings:
            mock_settings.mcpgateway_direct_proxy_enabled = False
            with patch("mcpgateway.transports.streamablehttp_transport.resource_service") as mock_rs:
                mock_rs.list_server_resources = AsyncMock(return_value=[])

                # This triggers the check failing on settings.mcpgateway_direct_proxy_enabled
                await list_resources()

                # Should fall back to cache mode
                mock_rs.list_server_resources.assert_called_once()

    server_id_var.reset(server_token)
    request_headers_var.reset(headers_token)


@pytest.mark.asyncio
async def test_list_resources_gateway_not_found_log(monkeypatch, caplog):
    """Test list_resources logs warning when gateway ID provided but not found."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_resources, request_headers_var, server_id_var

    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

    @asynccontextmanager
    async def mock_get_db():
        yield mock_db

    server_token = server_id_var.set("server-123")
    headers_token = request_headers_var.set({"x-context-forge-gateway-id": "gw-missing"})

    with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
        with patch("mcpgateway.transports.streamablehttp_transport.resource_service") as mock_rs:
            mock_rs.list_server_resources = AsyncMock(return_value=[])

            with caplog.at_level("WARNING", logger="mcpgateway.transports.streamablehttp_transport"):
                await list_resources()
                # Case-insensitive check or matching the exact log output
                assert "Gateway gw-missing specified in X-Context-Forge-Gateway-Id header not found" in caplog.text

    server_id_var.reset(server_token)
    request_headers_var.reset(headers_token)


@pytest.mark.asyncio
async def test_list_resources_direct_proxy_meta_lookup_error(monkeypatch):
    """Test list_resources in direct_proxy mode when request_context raises LookupError."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_resources, mcp_app, request_headers_var, server_id_var

    mock_gateway = MagicMock()
    mock_gateway.id = "gw-direct"
    mock_gateway.gateway_mode = "direct_proxy"

    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway)))

    @asynccontextmanager
    async def mock_get_db():
        yield mock_db

    server_token = server_id_var.set("server-123")
    headers_token = request_headers_var.set({"x-context-forge-gateway-id": "gw-direct"})

    with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
        with patch("mcpgateway.transports.streamablehttp_transport.settings") as mock_settings:
            mock_settings.mcpgateway_direct_proxy_enabled = True
            with patch("mcpgateway.transports.streamablehttp_transport.check_gateway_access", return_value=True):
                with patch("mcpgateway.transports.streamablehttp_transport._proxy_list_resources_to_gateway") as mock_proxy:
                    mock_proxy.return_value = []

                    # Force LookupError when accessing request_context
                    original_prop = type(mcp_app).__dict__.get("request_context")
                    type(mcp_app).request_context = property(lambda self: (_ for _ in ()).throw(LookupError("No context")))

                    try:
                        await list_resources()

                        # Verify called with meta=None
                        mock_proxy.assert_awaited_once()
                        args = mock_proxy.call_args[0]
                        # signature: (gateway, request_headers, user_context, meta)
                        assert args[3] is None
                    finally:
                        if original_prop is not None:
                            type(mcp_app).request_context = original_prop
                        elif "request_context" in type(mcp_app).__dict__:
                            delattr(type(mcp_app), "request_context")

    server_id_var.reset(server_token)
    request_headers_var.reset(headers_token)


# ---------------------------------------------------------------------------
# _get_request_context_or_default
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_request_context_no_request_object(monkeypatch, caplog):
    """Test _get_request_context_or_default when context exists but request is None (lines 985-986)."""
    # Standard
    from unittest.mock import PropertyMock

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _get_request_context_or_default, mcp_app, server_id_var

    token = server_id_var.set("default_server_id")

    mock_ctx = MagicMock()
    mock_ctx.request = None

    try:
        with patch.object(type(mcp_app), "request_context", new_callable=PropertyMock, return_value=mock_ctx):
            with caplog.at_level("WARNING", logger="mcpgateway.transports.streamablehttp_transport"):
                sid, headers, user = await _get_request_context_or_default()

                assert sid == "default_server_id"
                assert "No request object found in MCP context" in caplog.text
    finally:
        server_id_var.reset(token)


@pytest.mark.asyncio
async def test_get_request_context_stateful_success(monkeypatch):
    """Test _get_request_context_or_default success path with server_id and auth (lines 988-1010)."""
    # Standard
    from unittest.mock import PropertyMock

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _get_request_context_or_default, mcp_app, server_id_var

    token = server_id_var.set("default_server_id")

    # Use a HEX server ID because the regex enforces [a-fA-F0-9\-]+
    valid_hex_id = "abc-123-def-456"

    mock_request = MagicMock()
    mock_request.url.path = f"/servers/{valid_hex_id}/mcp"
    mock_request.headers = {"authorization": "Bearer token"}
    mock_request.cookies = {}

    mock_ctx = MagicMock()
    mock_ctx.request = mock_request

    # Use realistic JWT payload shape (raw from require_auth_header_first)
    raw_jwt = {"sub": "test_user@example.com", "token_use": "api", "teams": ["team-1"]}
    mock_auth_override = AsyncMock(return_value=raw_jwt)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.require_auth_header_first", mock_auth_override)

    # Mock normalization to avoid DB/cache dependencies
    normalized = {"email": "test_user@example.com", "teams": ["team-1"], "is_admin": False, "is_authenticated": True}
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._normalize_jwt_payload", AsyncMock(side_effect=lambda payload: normalized))

    try:
        with patch.object(type(mcp_app), "request_context", new_callable=PropertyMock, return_value=mock_ctx):
            sid, headers, user = await _get_request_context_or_default()

            # Verify server_id extracted from URL
            assert sid == valid_hex_id
            assert headers["authorization"] == "Bearer token"
            assert user == normalized
    finally:
        server_id_var.reset(token)


@pytest.mark.asyncio
async def test_get_request_context_auth_failure(monkeypatch, caplog):
    """Test _get_request_context_or_default handles auth exception (lines 1006-1008)."""
    # Standard
    from unittest.mock import PropertyMock

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _get_request_context_or_default, mcp_app, server_id_var

    token = server_id_var.set("default_server_id")

    mock_request = MagicMock()
    mock_request.url.path = "/mcp"  # No server ID
    mock_request.headers = {}
    mock_request.cookies = {}

    mock_ctx = MagicMock()
    mock_ctx.request = mock_request

    mock_auth_override = AsyncMock(side_effect=Exception("Auth failed"))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.require_auth_header_first", mock_auth_override)

    try:
        with patch.object(type(mcp_app), "request_context", new_callable=PropertyMock, return_value=mock_ctx):
            with caplog.at_level("WARNING", logger="mcpgateway.transports.streamablehttp_transport"):
                sid, headers, user = await _get_request_context_or_default()

                assert sid == "default_server_id"
                assert user == {}
                assert "Failed to recover user context" in caplog.text
    finally:
        server_id_var.reset(token)


# ---------------------------------------------------------------------------
# handle_streamable_http injection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_affinity_post_injects_server_id(monkeypatch):
    """Test handle_streamable_http injects server_id into params for local affinity (lines 1956-1960)."""
    # Third-Party
    import orjson

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import SessionManagerWrapper

    # Setup mocks for SessionManagerWrapper
    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            pass

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    monkeypatch.setattr("mcpgateway.services.server_service.ServerService.entity_exists", AsyncMock(return_value=True))
    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    # Use a HEX server ID because the regex enforces [a-fA-F0-9\-]+
    server_id = "abc-123-def-456"
    scope = _make_scope(f"/servers/{server_id}/mcp", method="POST", headers=[(b"mcp-session-id", b"sess-1")])

    original_body = orjson.dumps({"jsonrpc": "2.0", "method": "test", "params": {}})
    receive = _make_receive(original_body)
    send, messages = _make_send_collector()

    mock_pool = MagicMock()
    mock_pool.get_streamable_http_session_owner = AsyncMock(return_value="worker-1")

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"{}"

    with patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool):
        with patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "worker-1"):
            with patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class):
                with patch("mcpgateway.transports.streamablehttp_transport.httpx.AsyncClient") as mock_client_cls:
                    mock_client = AsyncMock()
                    mock_client.post = AsyncMock(return_value=mock_response)
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock(return_value=None)
                    mock_client_cls.return_value = mock_client

                    await wrapper.handle_streamable_http(scope, receive, send)

                    mock_client.post.assert_called_once()
                    posted_content = mock_client.post.call_args.kwargs["content"]
                    posted_json = orjson.loads(posted_content)

                    assert "server_id" in posted_json["params"]
                    assert posted_json["params"]["server_id"] == server_id

    await wrapper.shutdown()


@pytest.mark.asyncio
async def test_handle_streamable_http_server_scope_requires_servers_use(monkeypatch):
    """Server-scoped Streamable HTTP requests must enforce servers.use before dispatch."""
    # Third-Party
    import orjson

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import SessionManagerWrapper, user_context_var

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            pass

    dummy_manager = DummySessionManager()
    dummy_manager.handle_request = AsyncMock()

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.StreamableHTTPSessionManager", lambda **kwargs: dummy_manager)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", False)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    token = user_context_var.set({"email": "dev@example.com", "teams": ["team-1"], "is_admin": False, "is_authenticated": True})
    try:
        monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._check_streamable_permission", AsyncMock(return_value=False))

        scope = _make_scope("/servers/abc-123-def/mcp", method="POST", headers=[(b"mcp-session-id", b"sess-1")])
        receive = _make_receive(orjson.dumps({"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": "1"}))
        send, messages = _make_send_collector()

        await wrapper.handle_streamable_http(scope, receive, send)

        assert messages and messages[0]["type"] == "http.response.start"
        assert messages[0]["status"] == tr.HTTP_403_FORBIDDEN
        dummy_manager.handle_request.assert_not_awaited()
    finally:
        user_context_var.reset(token)
        await wrapper.shutdown()


@pytest.mark.asyncio
async def test_handle_streamable_http_server_scope_checks_any_team_for_team_api_token(monkeypatch):
    """Server-scoped MCP requests should check RBAC across token teams for API tokens."""
    # Third-Party
    import orjson

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import SessionManagerWrapper, user_context_var

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            pass

    dummy_manager = DummySessionManager()
    dummy_manager.handle_request = AsyncMock()

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.StreamableHTTPSessionManager", lambda **kwargs: dummy_manager)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", False)

    permission_check = AsyncMock(return_value=True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._check_streamable_permission", permission_check)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    token = user_context_var.set(
        {
            "email": "dev@example.com",
            "teams": ["team-1"],
            "is_admin": False,
            "is_authenticated": True,
            "token_use": "api",
        }
    )
    try:
        scope = _make_scope("/servers/abc-123-def/mcp", method="POST", headers=[(b"mcp-session-id", b"sess-1")])
        receive = _make_receive(orjson.dumps({"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": "1"}))
        send, _messages = _make_send_collector()

        await wrapper.handle_streamable_http(scope, receive, send)

        assert permission_check.await_args.kwargs["permission"] == "servers.use"
        assert permission_check.await_args.kwargs["check_any_team"] is True
    finally:
        user_context_var.reset(token)
        await wrapper.shutdown()


@pytest.mark.parametrize(
    ("user_context", "server_id", "expected"),
    [
        (None, "srv-1", False),
        ({"token_use": "session", "teams": []}, None, True),
        ({"token_use": "api", "teams": ["team-1"]}, "srv-1", True),
        ({"token_use": "api", "teams": []}, "srv-1", False),
        ({"token_use": "api", "teams": ["team-1"]}, None, False),
    ],
)
def test_check_any_team_for_server_scoped_rbac(user_context, server_id, expected):
    """Server-scoped RBAC should reuse any-team lookup for session and team API tokens."""
    assert tr._check_any_team_for_server_scoped_rbac(user_context, server_id) is expected


# ---------------------------------------------------------------------------
# streamable_http_auth exception fallbacks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streamable_http_auth_verify_exception_fallback_permissive(monkeypatch):
    """Bearer verification errors should return 401 even in permissive mode without proxy fallback."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import streamable_http_auth, user_context_var

    # Force verify_credentials to raise HTTPException (its actual failure mode)
    monkeypatch.setattr(tr, "verify_credentials", AsyncMock(side_effect=HTTPException(status_code=401, detail="Auth Service Down")))

    # Settings: Trust proxy is ON, but we won't provide header. Require auth is OFF (permissive).
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.trust_proxy_auth", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.trust_proxy_auth_dangerously", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.proxy_user_header", "x-user")
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", False)

    scope = _make_scope("/servers/abc-123/mcp", headers=[(b"authorization", b"Bearer bad-token")])
    sent = []

    async def send(msg):
        sent.append(msg)

    # Should catch exception, fail proxy fallback (no proxy header), and reject invalid bearer.
    result = await streamable_http_auth(scope, None, send)

    assert result is False
    assert sent and sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == tr.HTTP_401_UNAUTHORIZED

    ctx = user_context_var.get()
    assert ctx is not None


# ---------------------------------------------------------------------------
# _get_request_context_or_default: additional coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_request_context_fast_path():
    """Fast path: returns ContextVars directly when server_id is not the default."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import (
        _get_request_context_or_default,
        request_headers_var,
        server_id_var,
        user_context_var,
    )

    s_tok = server_id_var.set("real-server-abc123")
    h_tok = request_headers_var.set({"authorization": "Bearer xyz"})
    u_tok = user_context_var.set({"email": "user@test.com", "teams": ["t1"]})

    try:
        sid, headers, user = await _get_request_context_or_default()
        assert sid == "real-server-abc123"
        assert headers == {"authorization": "Bearer xyz"}
        assert user == {"email": "user@test.com", "teams": ["t1"]}
    finally:
        server_id_var.reset(s_tok)
        request_headers_var.reset(h_tok)
        user_context_var.reset(u_tok)


@pytest.mark.asyncio
async def test_get_request_context_anonymous_user(monkeypatch):
    """Auth returning 'anonymous' string is converted to empty dict."""
    # Standard
    from unittest.mock import PropertyMock

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _get_request_context_or_default, mcp_app, server_id_var

    token = server_id_var.set("default_server_id")

    mock_request = MagicMock()
    mock_request.url.path = "/servers/abc-def-123/mcp"
    mock_request.headers = {}
    mock_request.cookies = {}

    mock_ctx = MagicMock()
    mock_ctx.request = mock_request

    mock_auth = AsyncMock(return_value="anonymous")
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.require_auth_header_first", mock_auth)

    try:
        with patch.object(type(mcp_app), "request_context", new_callable=PropertyMock, return_value=mock_ctx):
            sid, headers, user = await _get_request_context_or_default()
            assert sid == "abc-def-123"
            assert user == {}  # "anonymous" string converted to empty dict
    finally:
        server_id_var.reset(token)


@pytest.mark.asyncio
async def test_get_request_context_url_without_server_id(monkeypatch):
    """Fallback path with URL that doesn't contain a server_id keeps default."""
    # Standard
    from unittest.mock import PropertyMock

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _get_request_context_or_default, mcp_app, server_id_var

    token = server_id_var.set("default_server_id")

    mock_request = MagicMock()
    mock_request.url.path = "/mcp"  # No /servers/{id}/mcp pattern
    mock_request.headers = {"x-custom": "value"}
    mock_request.cookies = {}

    mock_ctx = MagicMock()
    mock_ctx.request = mock_request

    # Use realistic JWT payload shape (raw from require_auth_header_first)
    raw_jwt = {"sub": "test@example.com", "token_use": "api"}
    mock_auth = AsyncMock(return_value=raw_jwt)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.require_auth_header_first", mock_auth)

    # Mock normalization to avoid DB/cache dependencies
    normalized = {"email": "test@example.com", "teams": [], "is_admin": False, "is_authenticated": True}
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._normalize_jwt_payload", AsyncMock(side_effect=lambda payload: normalized))

    try:
        with patch.object(type(mcp_app), "request_context", new_callable=PropertyMock, return_value=mock_ctx):
            sid, headers, user = await _get_request_context_or_default()
            assert sid == "default_server_id"  # No match, keeps default
            assert headers["x-custom"] == "value"
            assert user == normalized
    finally:
        server_id_var.reset(token)


@pytest.mark.asyncio
async def test_get_request_context_lookup_error_fallback():
    """LookupError from mcp_app.request_context returns ContextVar defaults."""
    # Standard
    from unittest.mock import PropertyMock

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import (
        _get_request_context_or_default,
        mcp_app,
        request_headers_var,
        server_id_var,
        user_context_var,
    )

    s_tok = server_id_var.set("default_server_id")
    h_tok = request_headers_var.set({"x-fallback": "true"})
    u_tok = user_context_var.set({"fallback": True})

    try:
        with patch.object(type(mcp_app), "request_context", new_callable=PropertyMock, side_effect=LookupError("No context")):
            sid, headers, user = await _get_request_context_or_default()
            assert sid == "default_server_id"
            assert headers == {"x-fallback": "true"}
            assert user == {"fallback": True}
    finally:
        server_id_var.reset(s_tok)
        request_headers_var.reset(h_tok)
        user_context_var.reset(u_tok)


@pytest.mark.asyncio
async def test_get_request_context_generic_exception_fallback(caplog):
    """Generic exception from request_context access returns defaults and logs error."""
    # Standard
    from unittest.mock import PropertyMock

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import (
        _get_request_context_or_default,
        mcp_app,
        request_headers_var,
        server_id_var,
        user_context_var,
    )

    s_tok = server_id_var.set("default_server_id")
    h_tok = request_headers_var.set({"x-default": "yes"})
    u_tok = user_context_var.set({})

    try:
        with patch.object(type(mcp_app), "request_context", new_callable=PropertyMock, side_effect=RuntimeError("Unexpected")):
            with caplog.at_level("ERROR"):
                sid, headers, user = await _get_request_context_or_default()
                assert sid == "default_server_id"
                assert headers == {"x-default": "yes"}
                assert user == {}
                assert "Error recovering context in stateful session" in caplog.text
    finally:
        server_id_var.reset(s_tok)
        request_headers_var.reset(h_tok)
        user_context_var.reset(u_tok)


@pytest.mark.asyncio
async def test_get_request_context_cookie_token_used(monkeypatch):
    """Cookie JWT token is passed to require_auth_header_first when present and no header."""
    # Standard
    from unittest.mock import PropertyMock

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _get_request_context_or_default, mcp_app, server_id_var

    token = server_id_var.set("default_server_id")

    mock_request = MagicMock()
    mock_request.url.path = "/servers/aabbcc-112233/mcp"
    mock_request.headers = {}  # No authorization header
    mock_request.cookies = {"jwt_token": "cookie-jwt-value"}

    mock_ctx = MagicMock()
    mock_ctx.request = mock_request

    # Use realistic JWT payload shape (raw from require_auth_header_first)
    raw_jwt = {"sub": "cookie-user@test.com", "token_use": "session"}
    mock_auth = AsyncMock(return_value=raw_jwt)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.require_auth_header_first", mock_auth)

    # Mock normalization to avoid DB/cache dependencies
    normalized = {"email": "cookie-user@test.com", "teams": [], "is_admin": False, "is_authenticated": True}
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._normalize_jwt_payload", AsyncMock(side_effect=lambda payload: normalized))

    try:
        with patch.object(type(mcp_app), "request_context", new_callable=PropertyMock, return_value=mock_ctx):
            sid, headers, user = await _get_request_context_or_default()
            assert sid == "aabbcc-112233"
            assert user == normalized
            # Verify cookie token was passed
            mock_auth.assert_awaited_once_with(auth_header=None, jwt_token="cookie-jwt-value", request=mock_request)
    finally:
        server_id_var.reset(token)


@pytest.mark.asyncio
async def test_get_request_context_header_wins_over_cookie(monkeypatch):
    """Identity drift fix: Authorization header token is used when both header and cookie JWT present.

    This test reproduces the bug where _get_request_context_or_default used
    cookie-first precedence (via require_auth_override -> require_auth) while
    streamable_http_auth middleware used header-first.  After the fix, the
    fallback must match the middleware: header beats cookie.
    """
    # Standard
    from unittest.mock import PropertyMock

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _get_request_context_or_default, mcp_app, server_id_var
    import mcpgateway.utils.verify_credentials as vc

    t = server_id_var.set("default_server_id")

    mock_request = MagicMock()
    mock_request.url.path = "/servers/aabb-ccdd-1234/mcp"
    mock_request.headers = {"authorization": "Bearer header-token-value"}
    mock_request.cookies = {"jwt_token": "cookie-token-value"}

    mock_ctx = MagicMock()
    mock_ctx.request = mock_request

    # Capture which token reaches verify_credentials_cached
    captured_tokens: list[str] = []

    async def fake_verify(token, request=None):
        captured_tokens.append(token)
        return {"sub": "verified-user", "aud": "mcpgateway-api"}

    monkeypatch.setattr(vc, "verify_credentials_cached", fake_verify)
    monkeypatch.setattr(vc.settings, "mcp_client_auth_enabled", True, raising=False)
    monkeypatch.setattr(vc.settings, "auth_required", True, raising=False)
    monkeypatch.setattr(vc.settings, "docs_allow_basic_auth", False, raising=False)

    normalized = {"email": "verified-user", "teams": [], "is_admin": False, "is_authenticated": True}
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._normalize_jwt_payload", AsyncMock(side_effect=lambda payload: normalized))

    try:
        with patch.object(type(mcp_app), "request_context", new_callable=PropertyMock, return_value=mock_ctx):
            sid, headers, user = await _get_request_context_or_default()

            assert captured_tokens, "verify_credentials_cached was never called"
            assert captured_tokens[0] == "header-token-value", (
                f"Expected header token to be used, got {captured_tokens[0]!r}. " "Cookie-first bug: cookie token was used instead of Authorization header."
            )
            assert user == normalized
    finally:
        server_id_var.reset(t)


# ---------------------------------------------------------------------------
# _normalize_jwt_payload tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_normalize_jwt_payload_api_token(monkeypatch):
    """API token (no token_use or token_use != 'session') uses normalize_token_teams."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _normalize_jwt_payload

    monkeypatch.setattr("mcpgateway.auth.normalize_token_teams", lambda payload: ["team-a"])

    raw = {"sub": "user@example.com", "token_use": "api", "teams": ["team-a"]}
    result = await _normalize_jwt_payload(raw)
    assert result == {"email": "user@example.com", "teams": ["team-a"], "is_admin": False, "is_authenticated": True, "token_use": "api"}


@pytest.mark.asyncio
async def test_normalize_jwt_payload_session_token_admin():
    """Session token with is_admin=True gets admin bypass (teams=None)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _normalize_jwt_payload

    raw = {"sub": "admin@example.com", "token_use": "session", "is_admin": True}
    with patch("mcpgateway.auth.resolve_session_teams", new_callable=AsyncMock, return_value=None):
        result = await _normalize_jwt_payload(raw)
    assert result == {"email": "admin@example.com", "teams": None, "is_admin": True, "is_authenticated": True, "token_use": "session"}


@pytest.mark.asyncio
async def test_normalize_jwt_payload_session_token_non_admin():
    """Session token without admin resolves teams from DB."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _normalize_jwt_payload

    raw = {"sub": "dev@example.com", "token_use": "session"}
    with patch("mcpgateway.auth.resolve_session_teams", new_callable=AsyncMock, return_value=["team-x"]):
        result = await _normalize_jwt_payload(raw)
    assert result == {"email": "dev@example.com", "teams": ["team-x"], "is_admin": False, "is_authenticated": True, "token_use": "session"}


@pytest.mark.asyncio
async def test_normalize_jwt_payload_nested_is_admin():
    """Nested user.is_admin is detected when top-level is_admin is absent."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _normalize_jwt_payload

    raw = {"sub": "nested-admin@example.com", "token_use": "session", "user": {"is_admin": True}}
    with patch("mcpgateway.auth.resolve_session_teams", new_callable=AsyncMock, return_value=None):
        result = await _normalize_jwt_payload(raw)
    assert result["is_admin"] is True
    assert result["teams"] is None  # Admin bypass


@pytest.mark.asyncio
async def test_normalize_jwt_payload_email_fallback():
    """Falls back to 'email' key when 'sub' is missing."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _normalize_jwt_payload

    raw = {"email": "legacy@example.com", "token_use": "session", "is_admin": True}
    with patch("mcpgateway.auth.resolve_session_teams", new_callable=AsyncMock, return_value=None):
        result = await _normalize_jwt_payload(raw)
    assert result["email"] == "legacy@example.com"


@pytest.mark.asyncio
async def test_normalize_jwt_payload_session_no_email():
    """Session token without email/sub gets public-only teams."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _normalize_jwt_payload

    raw = {"token_use": "session"}
    # resolve_session_teams returns [] for no-email
    with patch("mcpgateway.auth.resolve_session_teams", new_callable=AsyncMock, return_value=[]):
        result = await _normalize_jwt_payload(raw)
    assert result == {"email": None, "teams": [], "is_admin": False, "is_authenticated": True, "token_use": "session"}


@pytest.mark.asyncio
async def test_normalize_jwt_payload_session_admin_no_email_no_bypass():
    """Admin session token without email/sub gets public-only, never admin bypass."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _normalize_jwt_payload

    raw = {"token_use": "session", "is_admin": True}
    # resolve_session_teams returns [] for no-email (even admin)
    with patch("mcpgateway.auth.resolve_session_teams", new_callable=AsyncMock, return_value=[]):
        result = await _normalize_jwt_payload(raw)
    # teams must be [] (public-only), NOT None (admin bypass)
    assert result["teams"] == []
    assert result["is_admin"] is True


# ---------------------------------------------------------------------------
# call_tool: recovered context propagation regression test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_tool_uses_recovered_email_not_stale_contextvar(monkeypatch):
    """call_tool passes app_user_email from recovered fallback context, not stale ContextVar.

    Regression test: previously call_tool used get_user_email_from_context()
    which reads from user_context_var (stale in stateful sessions). Now it
    extracts email from the already-recovered user_context dict.
    """
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, user_context_var

    # Set ContextVar to a STALE email that should NOT be used
    stale_ctx = {"email": "stale-user@old.com", "teams": [], "is_admin": False, "is_authenticated": True}
    u_tok = user_context_var.set(stale_ctx)

    # The recovered context should provide a DIFFERENT email
    recovered_ctx = {"email": "recovered-user@new.com", "teams": ["team-1"], "is_admin": False, "is_authenticated": True}

    # Mock _get_request_context_or_default to return the recovered context
    async def fake_get_context():
        return "test-server-id", {"authorization": "Bearer token"}, recovered_ctx

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._get_request_context_or_default", fake_get_context)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda h: None)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", False)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._check_scoped_permission", lambda *a, **k: True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._check_streamable_permission", AsyncMock(return_value=True))

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_content = MagicMock()
    mock_content.type = "text"
    mock_content.text = "ok"
    mock_content.annotations = None
    mock_content.meta = None
    mock_result.content = [mock_content]
    mock_result.structured_content = None
    mock_result.model_dump = lambda by_alias=True: {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    invoke_mock = AsyncMock(return_value=mock_result)
    monkeypatch.setattr(tool_service, "invoke_tool", invoke_mock)

    try:
        await call_tool("test-tool", {"arg": "val"})

        # Assert invoke_tool was called with the RECOVERED email, not the stale one
        invoke_mock.assert_awaited_once()
        call_kwargs = invoke_mock.call_args.kwargs
        assert call_kwargs["app_user_email"] == "recovered-user@new.com", f"Expected recovered email but got: {call_kwargs['app_user_email']}"
        assert call_kwargs["user_email"] == "recovered-user@new.com"
        assert call_kwargs["token_teams"] == ["team-1"]
    finally:
        user_context_var.reset(u_tok)


# ---------------------------------------------------------------------------
# handle_streamable_http injection: additional coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_affinity_post_injects_server_id_when_params_missing(monkeypatch):
    """server_id injection creates params dict when absent from JSON-RPC body."""
    # Third-Party
    import orjson

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import SessionManagerWrapper

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            pass

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    monkeypatch.setattr("mcpgateway.services.server_service.ServerService.entity_exists", AsyncMock(return_value=True))
    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    server_id = "abc-123-def-456"
    # JSON-RPC body WITHOUT params key
    original_body = orjson.dumps({"jsonrpc": "2.0", "method": "tools/list", "id": 1})
    scope = _make_scope(f"/servers/{server_id}/mcp", method="POST", headers=[(b"mcp-session-id", b"sess-1")])
    receive = _make_receive(original_body)
    send, messages = _make_send_collector()

    mock_pool = MagicMock()
    mock_pool.get_streamable_http_session_owner = AsyncMock(return_value="worker-1")

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"{}"

    with patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool):
        with patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "worker-1"):
            with patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class):
                with patch("mcpgateway.transports.streamablehttp_transport.httpx.AsyncClient") as mock_client_cls:
                    mock_client = AsyncMock()
                    mock_client.post = AsyncMock(return_value=mock_response)
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock(return_value=None)
                    mock_client_cls.return_value = mock_client

                    await wrapper.handle_streamable_http(scope, receive, send)

                    mock_client.post.assert_called_once()
                    posted_content = mock_client.post.call_args.kwargs["content"]
                    posted_json = orjson.loads(posted_content)

                    # params was created and server_id injected
                    assert "params" in posted_json
                    assert posted_json["params"]["server_id"] == server_id

    await wrapper.shutdown()


@pytest.mark.asyncio
async def test_local_affinity_post_no_injection_without_server_url(monkeypatch):
    """No server_id injection when URL does not match /servers/{id}/mcp pattern."""
    # Third-Party
    import orjson

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import SessionManagerWrapper

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            pass

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    # URL without /servers/{id}/mcp pattern
    original_body = orjson.dumps({"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 1})
    scope = _make_scope("/mcp", method="POST", headers=[(b"mcp-session-id", b"sess-1")])
    receive = _make_receive(original_body)
    send, messages = _make_send_collector()

    mock_pool = MagicMock()
    mock_pool.get_streamable_http_session_owner = AsyncMock(return_value="worker-1")

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"{}"

    with patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool):
        with patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "worker-1"):
            with patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class):
                with patch("mcpgateway.transports.streamablehttp_transport.httpx.AsyncClient") as mock_client_cls:
                    mock_client = AsyncMock()
                    mock_client.post = AsyncMock(return_value=mock_response)
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock(return_value=None)
                    mock_client_cls.return_value = mock_client

                    await wrapper.handle_streamable_http(scope, receive, send)

                    mock_client.post.assert_called_once()
                    posted_content = mock_client.post.call_args.kwargs["content"]
                    posted_json = orjson.loads(posted_content)

                    # No server_id injected
                    assert "server_id" not in posted_json.get("params", {})

    await wrapper.shutdown()


# ---------------------------------------------------------------------------
# _rehydrate_content_items and content serialization — JSON correctness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_tool_rehydrate_unknown_type_produces_valid_json(monkeypatch):
    """When _rehydrate_content_items encounters an unknown content type dict, it should serialize as valid JSON."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import (
        call_tool,
        request_headers_var,
        types,
        user_context_var,
    )

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)

    h_token = request_headers_var.set({"mcp-session-id": "abc-123-valid-session"})
    u_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})

    mock_pool = MagicMock()
    mock_pool.forward_request_to_owner = AsyncMock(
        return_value={
            "result": {
                "content": [
                    {"type": "custom_widget", "data": {"enabled": False, "count": 42}},
                ],
            },
        }
    )
    mock_pool.register_session_mapping = AsyncMock()

    mock_cache = AsyncMock()
    mock_cache.get = AsyncMock(return_value={"status": "active", "gateway": {"url": "http://gw:9000", "id": "g1", "transport": "streamablehttp"}})

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    try:
        with (
            patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
            patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
            patch("mcpgateway.cache.tool_lookup_cache.tool_lookup_cache", mock_cache),
        ):
            result = await call_tool("my_tool", {"arg": "val"})
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], types.TextContent)
        text = result[0].text
        parsed = json.loads(text)
        assert parsed["data"]["enabled"] is False
        assert "False" not in text
    finally:
        request_headers_var.reset(h_token)
        user_context_var.reset(u_token)


@pytest.mark.asyncio
async def test_call_tool_rehydrate_fallback_on_validation_error(monkeypatch):
    """When model_validate fails for a known type, fallback should produce valid JSON."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import (
        call_tool,
        request_headers_var,
        types,
        user_context_var,
    )

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)

    h_token = request_headers_var.set({"mcp-session-id": "abc-123-valid-session"})
    u_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})

    mock_pool = MagicMock()
    mock_pool.forward_request_to_owner = AsyncMock(
        return_value={
            "result": {
                "content": [
                    {"type": "image", "invalid_field": True, "nested": {"active": False}},
                ],
            },
        }
    )
    mock_pool.register_session_mapping = AsyncMock()

    mock_cache = AsyncMock()
    mock_cache.get = AsyncMock(return_value={"status": "active", "gateway": {"url": "http://gw:9000", "id": "g1", "transport": "streamablehttp"}})

    mock_session_class = MagicMock()
    mock_session_class.is_valid_mcp_session_id = MagicMock(return_value=True)

    try:
        with (
            patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool),
            patch("mcpgateway.services.mcp_session_pool.MCPSessionPool", mock_session_class),
            patch("mcpgateway.cache.tool_lookup_cache.tool_lookup_cache", mock_cache),
        ):
            result = await call_tool("my_tool", {})
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], types.TextContent)
        text = result[0].text
        parsed = json.loads(text)
        assert parsed["invalid_field"] is True
        assert parsed["nested"]["active"] is False
        assert "False" not in text
        assert "True" not in text
    finally:
        request_headers_var.reset(h_token)
        user_context_var.reset(u_token)


@pytest.mark.asyncio
async def test_call_tool_unknown_content_type_local_path(monkeypatch):
    """When local invoke returns unknown content type, it should serialize as valid JSON via orjson."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, types

    mock_db = MagicMock()

    # Create a mock content object with unknown type
    mock_content = MagicMock()
    mock_content.type = "unknown_custom_type"
    mock_content.model_dump = MagicMock(return_value={"type": "unknown_custom_type", "payload": {"active": False, "items": [1, 2]}})
    mock_content.annotations = None
    mock_content.meta = None

    mock_result = MagicMock()
    mock_result.content = [mock_content]
    mock_result.structured_content = None
    mock_result.model_dump = lambda by_alias=True: {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    result = await call_tool("mytool", {})
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], types.TextContent)
    text = result[0].text
    parsed = json.loads(text)
    assert parsed["payload"]["active"] is False
    assert "False" not in text


# ---------------------------------------------------------------------------
# _check_server_oauth_enforcement tests (Bug #3304)
# ---------------------------------------------------------------------------


def _make_cm_db_mock(**execute_kwargs):
    """Create a MagicMock that works as ``session = SessionLocal(); with session.begin() as db: ...``."""
    mock_session = MagicMock(**execute_kwargs)
    mock_session.begin.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_session.begin.return_value.__exit__ = MagicMock(return_value=False)
    return mock_session


def _make_fake_get_db(mock_db):
    """Create a fake async ``get_db()`` context manager that yields *mock_db*."""

    @asynccontextmanager
    async def _fake():
        yield mock_db

    return _fake


class TestCheckServerOauthEnforcement:
    """Verify per-server OAuth enforcement via _check_server_oauth_enforcement."""

    @pytest.fixture(autouse=True)
    def _reset_oauth_checked(self):
        """Reset the _oauth_checked_var ContextVar between tests."""
        token = tr._oauth_checked_var.set(False)
        yield
        tr._oauth_checked_var.reset(token)

    @pytest.mark.asyncio
    async def test_no_server_id_is_noop(self):
        """No server context → nothing to enforce."""
        await tr._check_server_oauth_enforcement("", {"is_authenticated": False})
        await tr._check_server_oauth_enforcement("default_server_id", {"is_authenticated": False})

    @pytest.mark.asyncio
    async def test_authenticated_user_passes(self):
        """Authenticated callers are never blocked by oauth_enabled."""
        await tr._check_server_oauth_enforcement("abc123", {"is_authenticated": True})

    @pytest.mark.asyncio
    async def test_unauthenticated_oauth_enabled_raises(self, monkeypatch):
        """Unauthenticated caller + oauth_enabled server → OAuthRequiredError."""
        mock_server = MagicMock()
        mock_server.oauth_enabled = True

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_server

        monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", _make_fake_get_db(mock_db))

        with pytest.raises(OAuthRequiredError, match="OAuth authentication") as exc_info:
            await tr._check_server_oauth_enforcement("abc123", {"is_authenticated": False})
        assert exc_info.value.server_id == "abc123"

    @pytest.mark.asyncio
    async def test_unauthenticated_oauth_disabled_passes(self, monkeypatch):
        """Unauthenticated caller + oauth_enabled=False → allowed (permissive mode)."""
        mock_server = MagicMock()
        mock_server.oauth_enabled = False

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_server

        monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", _make_fake_get_db(mock_db))

        await tr._check_server_oauth_enforcement("abc123", {"is_authenticated": False})

    @pytest.mark.asyncio
    async def test_server_not_found_passes(self, monkeypatch):
        """Non-existent server → no enforcement (handled elsewhere)."""
        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", _make_fake_get_db(mock_db))

        await tr._check_server_oauth_enforcement("abc123", {"is_authenticated": False})

    @pytest.mark.asyncio
    async def test_none_user_context_treated_as_unauthenticated(self, monkeypatch):
        """None user_context → treated as unauthenticated."""
        mock_server = MagicMock()
        mock_server.oauth_enabled = True

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_server

        monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", _make_fake_get_db(mock_db))

        with pytest.raises(OAuthRequiredError, match="OAuth authentication"):
            await tr._check_server_oauth_enforcement("abc123", None)


# ---------------------------------------------------------------------------
# streamable_http_auth: per-server OAuth enforcement in permissive mode (#3304)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streamable_http_auth_rejects_unauthenticated_oauth_server(monkeypatch):
    """Permissive mode rejects unauthenticated requests to servers with oauth_enabled=True."""
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", False)

    mock_server = MagicMock()
    mock_server.oauth_enabled = True

    mock_db = MagicMock()
    mock_db.execute.return_value.scalar_one_or_none.return_value = mock_server

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", _make_fake_get_db(mock_db))

    scope = _make_scope("/servers/abc123def/mcp")
    called = []

    async def send(msg):
        called.append(msg)

    token = tr._oauth_checked_var.set(False)
    try:
        result = await streamable_http_auth(scope, None, send)
    finally:
        tr._oauth_checked_var.reset(token)
    assert result is False
    assert len(called) == 2  # response start + body
    assert called[0]["status"] == 401
    # Verify WWW-Authenticate includes resource_metadata URL per RFC 9728
    www_auth = dict(called[0].get("headers", [])).get(b"www-authenticate", b"").decode()
    assert "resource_metadata=" in www_auth
    assert "abc123def" in www_auth


@pytest.mark.asyncio
async def test_streamable_http_auth_allows_unauthenticated_non_oauth_server(monkeypatch):
    """Permissive mode allows unauthenticated requests to servers without oauth_enabled."""
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", False)

    mock_server = MagicMock()
    mock_server.oauth_enabled = False

    mock_db = MagicMock()
    mock_db.execute.return_value.scalar_one_or_none.return_value = mock_server

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", _make_fake_get_db(mock_db))

    scope = _make_scope("/servers/abc123def/mcp")
    called = []

    async def send(msg):
        called.append(msg)

    token = tr._oauth_checked_var.set(False)
    try:
        result = await streamable_http_auth(scope, None, send)
    finally:
        tr._oauth_checked_var.reset(token)
    assert result is True
    assert called == []


@pytest.mark.asyncio
async def test_streamable_http_auth_allows_authenticated_oauth_server(monkeypatch):
    """Authenticated requests to oauth_enabled servers pass through normally."""

    async def fake_verify(token):
        return {
            "sub": "user@example.com",
            "teams": ["team1"],
            "user": {"is_admin": False},
        }

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", False)

    # Mock auth_cache to return valid membership (skip DB lookup)
    mock_auth_cache = MagicMock()
    mock_auth_cache.get_team_membership_valid_sync.return_value = True

    scope = _make_scope("/servers/abc123def/mcp", headers=[(b"authorization", b"Bearer valid-token")])
    called = []

    async def send(msg):
        called.append(msg)

    with patch("mcpgateway.cache.auth_cache.get_auth_cache", return_value=mock_auth_cache):
        result = await streamable_http_auth(scope, None, send)
    assert result is True
    assert called == []

    user_ctx = tr.user_context_var.get()
    assert user_ctx.get("is_authenticated") is True


@pytest.mark.asyncio
async def test_streamable_http_auth_returns_503_on_db_failure(monkeypatch):
    """Middleware returns 503 when DB is unavailable (OAuthEnforcementUnavailableError)."""
    # Third-Party
    from sqlalchemy.exc import OperationalError

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", False)

    mock_db = MagicMock()
    mock_db.execute.side_effect = OperationalError("SELECT ...", {}, Exception("connection refused"))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", _make_fake_get_db(mock_db))

    scope = _make_scope("/servers/abc123def/mcp")
    called = []

    async def send(msg):
        called.append(msg)

    token = tr._oauth_checked_var.set(False)
    try:
        result = await streamable_http_auth(scope, None, send)
    finally:
        tr._oauth_checked_var.reset(token)
    assert result is False
    assert len(called) == 2  # response start + body
    assert called[0]["status"] == 503


# ---------------------------------------------------------------------------
# _check_server_oauth_enforcement: DB failure paths (fail-closed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_server_oauth_enforcement_db_query_failure_raises(monkeypatch):
    """DB query failure wraps in OAuthEnforcementUnavailableError — fail-closed."""
    # Third-Party
    from sqlalchemy.exc import OperationalError

    token = tr._oauth_checked_var.set(False)
    try:
        mock_db = MagicMock()
        mock_db.execute.side_effect = OperationalError("SELECT ...", {}, Exception("connection refused"))

        monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", _make_fake_get_db(mock_db))

        with pytest.raises(OAuthEnforcementUnavailableError) as exc_info:
            await tr._check_server_oauth_enforcement("abc123", {"is_authenticated": False})
        assert exc_info.value.server_id == "abc123"
        assert isinstance(exc_info.value.__cause__, OperationalError)
    finally:
        tr._oauth_checked_var.reset(token)


# ---------------------------------------------------------------------------
# Handler-level OAuth enforcement (lines 1330, 1432, 1491, 1563, 1656)
# These exercise the _check_server_oauth_enforcement call inside each handler
# when _should_enforce_streamable_rbac returns True (user_context has
# "is_authenticated" key).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tools_oauth_enforcement_with_authenticated_context(monkeypatch):
    """list_tools calls _check_server_oauth_enforcement when middleware context is present (line 1330)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_tools, server_id_var, tool_service, user_context_var

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", False)

    mock_db = MagicMock()
    mock_tool = MagicMock()
    mock_tool.name = "t"
    mock_tool.description = "desc"
    mock_tool.input_schema = {"type": "object"}
    mock_tool.output_schema = None
    mock_tool.annotations = {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "list_server_tools", AsyncMock(return_value=[mock_tool]))

    # Authenticated context triggers _should_enforce_streamable_rbac → True
    ctx_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_authenticated": True, "is_admin": False})
    sid_token = server_id_var.set("test-server")

    with patch.object(tr, "_check_server_oauth_enforcement") as mock_check:
        result = await list_tools()

    mock_check.assert_called_once_with("test-server", {"email": "user@test.com", "teams": ["t1"], "is_authenticated": True, "is_admin": False})
    assert len(result) == 1
    assert result[0].name == "t"

    user_context_var.reset(ctx_token)
    server_id_var.reset(sid_token)


@pytest.mark.asyncio
async def test_list_prompts_oauth_enforcement_with_authenticated_context(monkeypatch):
    """list_prompts calls _check_server_oauth_enforcement when middleware context is present (line 1432)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_prompts, server_id_var, user_context_var

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", False)

    mock_db = MagicMock()
    mock_prompt = MagicMock()
    mock_prompt.name = "p"
    mock_prompt.description = "prompt desc"
    mock_prompt.arguments = []

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tr.prompt_service, "list_server_prompts", AsyncMock(return_value=[mock_prompt]))

    ctx_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_authenticated": True, "is_admin": False})
    sid_token = server_id_var.set("test-server")

    with patch.object(tr, "_check_server_oauth_enforcement") as mock_check:
        result = await list_prompts()

    mock_check.assert_called_once_with("test-server", {"email": "user@test.com", "teams": ["t1"], "is_authenticated": True, "is_admin": False})
    assert len(result) == 1
    assert result[0].name == "p"

    user_context_var.reset(ctx_token)
    server_id_var.reset(sid_token)


@pytest.mark.asyncio
async def test_get_prompt_oauth_enforcement_with_authenticated_context(monkeypatch):
    """get_prompt calls _check_server_oauth_enforcement when middleware context is present (line 1491)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import get_prompt, server_id_var, user_context_var

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", False)

    mock_db = MagicMock()
    mock_message = MagicMock()
    mock_message.model_dump.return_value = {"role": "user", "content": {"type": "text", "text": "hi"}}
    mock_result = MagicMock()
    mock_result.messages = [mock_message]
    mock_result.description = "test prompt"

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tr.prompt_service, "get_prompt", AsyncMock(return_value=mock_result))

    ctx_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_authenticated": True, "is_admin": False})
    sid_token = server_id_var.set("test-server")

    with patch.object(tr, "_check_server_oauth_enforcement") as mock_check:
        result = await get_prompt("test-prompt", None)

    mock_check.assert_called_once_with("test-server", {"email": "user@test.com", "teams": ["t1"], "is_authenticated": True, "is_admin": False})
    assert result.description == "test prompt"

    user_context_var.reset(ctx_token)
    server_id_var.reset(sid_token)


@pytest.mark.asyncio
async def test_list_resources_oauth_enforcement_with_authenticated_context(monkeypatch):
    """list_resources calls _check_server_oauth_enforcement when middleware context is present (line 1563)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_resources, server_id_var, user_context_var

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", False)

    mock_db = MagicMock()
    mock_resource = MagicMock()
    mock_resource.uri = "file:///test"
    mock_resource.name = "r"
    mock_resource.description = "resource desc"
    mock_resource.mime_type = "text/plain"

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tr.resource_service, "list_server_resources", AsyncMock(return_value=[mock_resource]))

    ctx_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_authenticated": True, "is_admin": False})
    sid_token = server_id_var.set("test-server")

    with patch.object(tr, "_check_server_oauth_enforcement") as mock_check:
        result = await list_resources()

    mock_check.assert_called_once_with("test-server", {"email": "user@test.com", "teams": ["t1"], "is_authenticated": True, "is_admin": False})
    assert len(result) == 1
    assert result[0].name == "r"

    user_context_var.reset(ctx_token)
    server_id_var.reset(sid_token)


@pytest.mark.asyncio
async def test_read_resource_oauth_enforcement_with_authenticated_context(monkeypatch):
    """read_resource calls _check_server_oauth_enforcement when middleware context is present (line 1656)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import read_resource, server_id_var, user_context_var

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", False)

    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_result.blob = None
    mock_result.text = "hello"

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tr.resource_service, "read_resource", AsyncMock(return_value=mock_result))

    ctx_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_authenticated": True, "is_admin": False})
    sid_token = server_id_var.set("test-server")

    with patch.object(tr, "_check_server_oauth_enforcement") as mock_check:
        result = await read_resource("file:///test")

    mock_check.assert_called_once_with("test-server", {"email": "user@test.com", "teams": ["t1"], "is_authenticated": True, "is_admin": False})
    assert result == "hello"

    user_context_var.reset(ctx_token)
    server_id_var.reset(sid_token)


@pytest.mark.asyncio
async def test_call_tool_oauth_enforcement_with_authenticated_context(monkeypatch):
    """call_tool calls _check_server_oauth_enforcement in permissive mode."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", False)
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default",
        AsyncMock(
            return_value=(
                "test-server",
                {},
                {"email": "user@test.com", "teams": ["t1"], "is_admin": False, "is_authenticated": True},
            )
        ),
    )
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._check_streamable_permission", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", False)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda _headers: None)

    mock_db = MagicMock()
    mock_content = MagicMock()
    mock_content.type = "text"
    mock_content.text = "ok"
    mock_content.annotations = None
    mock_content.meta = None
    mock_result = MagicMock()
    mock_result.content = [mock_content]
    mock_result.structured_content = None
    mock_result.model_dump = lambda by_alias=True: {}

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    with patch.object(tr, "_check_server_oauth_enforcement") as mock_check:
        await call_tool("mytool", {"foo": "bar"})

    mock_check.assert_called_once_with("test-server", {"email": "user@test.com", "teams": ["t1"], "is_admin": False, "is_authenticated": True})


@pytest.mark.asyncio
async def test_list_resource_templates_oauth_enforcement_with_authenticated_context(monkeypatch):
    """list_resource_templates calls _check_server_oauth_enforcement in permissive mode."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_resource_templates, user_context_var

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", False)

    mock_db = MagicMock()
    mock_template = MagicMock()
    mock_template.model_dump = MagicMock(return_value={"uri_template": "file:///{path}", "name": "Files"})

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tr.resource_service, "list_resource_templates", AsyncMock(return_value=[mock_template]))

    ctx_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_authenticated": True, "is_admin": False})
    sid_token = tr.server_id_var.set("test-server")

    with patch.object(tr, "_check_server_oauth_enforcement") as mock_check:
        result = await list_resource_templates()

    mock_check.assert_called_once_with("test-server", {"email": "user@test.com", "teams": ["t1"], "is_authenticated": True, "is_admin": False})
    assert len(result) == 1

    user_context_var.reset(ctx_token)
    tr.server_id_var.reset(sid_token)


# ---------------------------------------------------------------------------
# _build_resource_metadata_url tests
# ---------------------------------------------------------------------------


class TestBuildResourceMetadataUrl:
    """Verify RFC 9728 resource metadata URL construction from ASGI scope."""

    def test_host_header(self):
        """Uses host header when present."""
        scope = _make_scope("/servers/s1/mcp", headers=[(b"host", b"example.com")])
        url = tr._build_resource_metadata_url(scope, "s1")
        assert url == "https://example.com/.well-known/oauth-protected-resource/servers/s1/mcp"

    def test_x_forwarded_proto(self):
        """Respects x-forwarded-proto header over scope scheme."""
        scope = _make_scope("/servers/s1/mcp", headers=[(b"host", b"example.com"), (b"x-forwarded-proto", b"http")])
        url = tr._build_resource_metadata_url(scope, "s1")
        assert url == "http://example.com/.well-known/oauth-protected-resource/servers/s1/mcp"

    def test_server_tuple_fallback(self):
        """Falls back to scope["server"] tuple when no host header."""
        scope: Scope = {
            "type": "http",
            "method": "POST",
            "path": "/servers/s1/mcp",
            "headers": [],
            "modified_path": "/servers/s1/mcp",
            "scheme": "https",
            "server": ("10.0.0.1", 8443),
        }
        url = tr._build_resource_metadata_url(scope, "s1")
        assert url == "https://10.0.0.1:8443/.well-known/oauth-protected-resource/servers/s1/mcp"

    def test_server_tuple_standard_port_https(self):
        """Standard HTTPS port (443) is excluded from host."""
        scope: Scope = {
            "type": "http",
            "method": "POST",
            "path": "/servers/s1/mcp",
            "headers": [],
            "modified_path": "/servers/s1/mcp",
            "scheme": "https",
            "server": ("example.com", 443),
        }
        url = tr._build_resource_metadata_url(scope, "s1")
        assert url == "https://example.com/.well-known/oauth-protected-resource/servers/s1/mcp"

    def test_server_tuple_standard_port_http(self):
        """Standard HTTP port (80) is excluded from host."""
        scope: Scope = {
            "type": "http",
            "method": "POST",
            "path": "/servers/s1/mcp",
            "headers": [],
            "modified_path": "/servers/s1/mcp",
            "scheme": "http",
            "server": ("example.com", 80),
        }
        url = tr._build_resource_metadata_url(scope, "s1")
        assert url == "http://example.com/.well-known/oauth-protected-resource/servers/s1/mcp"

    def test_server_tuple_nonstandard_port_included(self):
        """Non-standard port (e.g. 443 on HTTP) is included in host."""
        scope: Scope = {
            "type": "http",
            "method": "POST",
            "path": "/servers/s1/mcp",
            "headers": [],
            "modified_path": "/servers/s1/mcp",
            "scheme": "http",
            "server": ("example.com", 443),
        }
        url = tr._build_resource_metadata_url(scope, "s1")
        assert url == "http://example.com:443/.well-known/oauth-protected-resource/servers/s1/mcp"

    def test_root_path_included(self):
        """Includes root_path for deployments behind a reverse proxy with a path prefix."""
        scope: Scope = {
            "type": "http",
            "method": "POST",
            "path": "/servers/s1/mcp",
            "headers": [(b"host", b"example.com")],
            "modified_path": "/servers/s1/mcp",
            "scheme": "https",
            "server": ("example.com", 443),
            "root_path": "/gateway/v1",
        }
        url = tr._build_resource_metadata_url(scope, "s1")
        assert url == "https://example.com/gateway/v1/.well-known/oauth-protected-resource/servers/s1/mcp"

    def test_root_path_trailing_slash_stripped(self):
        """Trailing slash on root_path does not produce double slash."""
        scope: Scope = {
            "type": "http",
            "method": "POST",
            "path": "/servers/s1/mcp",
            "headers": [(b"host", b"example.com")],
            "modified_path": "/servers/s1/mcp",
            "scheme": "https",
            "server": ("example.com", 443),
            "root_path": "/gateway/v1/",
        }
        url = tr._build_resource_metadata_url(scope, "s1")
        assert url == "https://example.com/gateway/v1/.well-known/oauth-protected-resource/servers/s1/mcp"

    def test_empty_root_path_no_prefix(self):
        """Empty root_path produces no prefix (default deployment)."""
        scope = _make_scope("/servers/s1/mcp", headers=[(b"host", b"example.com")])
        url = tr._build_resource_metadata_url(scope, "s1")
        assert "//." not in url  # no double-slash before .well-known
        assert url == "https://example.com/.well-known/oauth-protected-resource/servers/s1/mcp"

    def test_empty_on_failure(self):
        """Returns empty string when no host info is available."""
        scope: Scope = {
            "type": "http",
            "method": "POST",
            "path": "/servers/s1/mcp",
            "headers": [],
            "modified_path": "/servers/s1/mcp",
            "scheme": "https",
        }
        url = tr._build_resource_metadata_url(scope, "s1")
        assert url == ""

    def test_ipv6_address_bracketed(self):
        """IPv6 addresses are wrapped in brackets per RFC 2732."""
        scope: Scope = {
            "type": "http",
            "method": "POST",
            "path": "/servers/s1/mcp",
            "headers": [],
            "modified_path": "/servers/s1/mcp",
            "scheme": "https",
            "server": ("::1", 4444),
        }
        url = tr._build_resource_metadata_url(scope, "s1")
        assert url == "https://[::1]:4444/.well-known/oauth-protected-resource/servers/s1/mcp"

    def test_ipv6_address_standard_port(self):
        """IPv6 on standard port omits port but keeps brackets."""
        scope: Scope = {
            "type": "http",
            "method": "POST",
            "path": "/servers/s1/mcp",
            "headers": [],
            "modified_path": "/servers/s1/mcp",
            "scheme": "https",
            "server": ("::1", 443),
        }
        url = tr._build_resource_metadata_url(scope, "s1")
        assert url == "https://[::1]/.well-known/oauth-protected-resource/servers/s1/mcp"


# ---------------------------------------------------------------------------
# _oauth_checked_var caching test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oauth_checked_var_caching(monkeypatch):
    """Second call to _check_server_oauth_enforcement skips DB when _oauth_checked_var is True."""
    mock_db = MagicMock()
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", _make_fake_get_db(mock_db))

    token = tr._oauth_checked_var.set(False)
    try:
        # First call: DB is accessed
        mock_server = MagicMock()
        mock_server.oauth_enabled = False
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_server

        await tr._check_server_oauth_enforcement("abc123", {"is_authenticated": False})
        assert mock_db.execute.call_count == 1

        # Second call: _oauth_checked_var is True, DB is NOT accessed again
        mock_db.execute.reset_mock()
        await tr._check_server_oauth_enforcement("abc123", {"is_authenticated": False})
        mock_db.execute.assert_not_called()
    finally:
        tr._oauth_checked_var.reset(token)


@pytest.mark.asyncio
async def test_streamable_http_auth_resets_oauth_checked_var(monkeypatch):
    """streamable_http_auth resets _oauth_checked_var so keep-alive requests re-check."""
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", False)

    mock_server = MagicMock()
    mock_server.oauth_enabled = True

    mock_db = MagicMock()
    mock_db.execute.return_value.scalar_one_or_none.return_value = mock_server
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", _make_fake_get_db(mock_db))

    # Simulate a stale True left over from a previous request on the same task context
    token = tr._oauth_checked_var.set(True)
    try:
        scope = _make_scope("/servers/abc123def/mcp")
        called = []

        async def send(msg):
            called.append(msg)

        result = await streamable_http_auth(scope, None, send)
        # Must still reject: the reset means the DB is re-checked
        assert result is False
        assert called[0]["status"] == 401
    finally:
        tr._oauth_checked_var.reset(token)


# ---------------------------------------------------------------------------
# Handler-level OAuth enforcement: set_logging_level and complete (#3304)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_logging_level_oauth_enforcement_with_authenticated_context(monkeypatch):
    """set_logging_level calls _check_server_oauth_enforcement in permissive mode."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import set_logging_level

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", False)
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default",
        AsyncMock(
            return_value=(
                "test-server",
                {},
                {"email": "user@test.com", "teams": ["t1"], "is_authenticated": True, "is_admin": True},
            )
        ),
    )
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._check_streamable_permission", AsyncMock(return_value=True))
    monkeypatch.setattr(tr.logging_service, "set_level", AsyncMock())

    with patch.object(tr, "_check_server_oauth_enforcement") as mock_check:
        await set_logging_level("info")

    mock_check.assert_called_once_with("test-server", {"email": "user@test.com", "teams": ["t1"], "is_authenticated": True, "is_admin": True})


@pytest.mark.asyncio
async def test_complete_oauth_enforcement_with_authenticated_context(monkeypatch):
    """complete calls _check_server_oauth_enforcement in permissive mode."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import complete

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", False)
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default",
        AsyncMock(
            return_value=(
                "test-server",
                {},
                {"email": "user@test.com", "teams": ["t1"], "is_authenticated": True, "is_admin": False},
            )
        ),
    )

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tr.completion_service, "handle_completion", AsyncMock(return_value={"completion": {"values": ["val1"], "total": 1, "hasMore": False}}))

    mock_ref = MagicMock()
    mock_ref.model_dump.return_value = {"type": "ref/prompt", "name": "test"}
    mock_arg = MagicMock()
    mock_arg.model_dump.return_value = {"name": "arg1", "value": "v"}

    with patch.object(tr, "_check_server_oauth_enforcement") as mock_check:
        await complete(mock_ref, mock_arg)

    mock_check.assert_called_once_with("test-server", {"email": "user@test.com", "teams": ["t1"], "is_authenticated": True, "is_admin": False})


@pytest.mark.asyncio
async def test_set_logging_level_oauth_enforcement_rejects_unauthenticated(monkeypatch):
    """OAuthRequiredError propagates out of set_logging_level (not swallowed)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import set_logging_level

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", False)
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default",
        AsyncMock(return_value=("oauth-server", {}, {"is_authenticated": False})),
    )

    mock_server = MagicMock()
    mock_server.oauth_enabled = True
    mock_db = MagicMock()
    mock_db.execute.return_value.scalar_one_or_none.return_value = mock_server
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", _make_fake_get_db(mock_db))

    token = tr._oauth_checked_var.set(False)
    try:
        with pytest.raises(OAuthRequiredError):
            await set_logging_level("info")
    finally:
        tr._oauth_checked_var.reset(token)


@pytest.mark.asyncio
async def test_complete_oauth_enforcement_rejects_unauthenticated(monkeypatch):
    """OAuthRequiredError propagates out of complete (not swallowed by broad except)."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import complete

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", False)
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default",
        AsyncMock(return_value=("oauth-server", {}, {"is_authenticated": False})),
    )

    mock_server = MagicMock()
    mock_server.oauth_enabled = True
    mock_db = MagicMock()
    mock_db.execute.return_value.scalar_one_or_none.return_value = mock_server
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", _make_fake_get_db(mock_db))

    mock_ref = MagicMock()
    mock_ref.model_dump.return_value = {"type": "ref/prompt", "name": "test"}
    mock_arg = MagicMock()
    mock_arg.model_dump.return_value = {"name": "arg1", "value": "v"}

    token = tr._oauth_checked_var.set(False)
    try:
        with pytest.raises(OAuthRequiredError):
            await complete(mock_ref, mock_arg)
    finally:
        tr._oauth_checked_var.reset(token)


# ---------------------------------------------------------------------------
# _build_resource_metadata_url: additional coverage
# ---------------------------------------------------------------------------


def test_build_resource_metadata_url_invalid_proto_fallback():
    """Invalid forwarded proto should fall back to https (line 476)."""
    scope = {
        "type": "http",
        "headers": [
            (b"x-forwarded-proto", b"ftp"),
            (b"host", b"example.com"),
        ],
    }
    url = tr._build_resource_metadata_url(scope, "srv-1")
    assert url.startswith("https://")
    assert "/servers/srv-1/mcp" in url


def test_build_resource_metadata_url_exception_returns_empty():
    """When scope is completely broken, function returns empty string (lines 493-494)."""
    url = tr._build_resource_metadata_url(None, "srv-1")
    assert url == ""


# ---------------------------------------------------------------------------
# _check_streamable_permission: exception path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_streamable_permission_exception_returns_false(monkeypatch):
    """RBAC check exception should log warning and return False (line 598)."""

    @asynccontextmanager
    async def exploding_db():
        raise RuntimeError("DB gone")
        yield  # noqa: unreachable — required for generator syntax

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", exploding_db)

    result = await tr._check_streamable_permission(
        user_context={"email": "user@example.com", "teams": ["t1"], "is_admin": False, "is_authenticated": True},
        permission="tools.execute",
    )
    assert result is False


# ---------------------------------------------------------------------------
# _claim_streamable_session_owner: exception path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_streamable_session_owner_exception_returns_none(monkeypatch):
    """Registry exception should log warning and return None (line 641)."""
    session_registry = MagicMock()
    session_registry.claim_session_owner = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._get_shared_session_registry", lambda: session_registry)

    result = await tr._claim_streamable_session_owner("sess-1", "user@example.com")
    assert result is None


# ---------------------------------------------------------------------------
# _validate_streamable_session_access: exception paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_session_access_get_owner_exception(monkeypatch):
    """get_session_owner exception should return 403 (line 684)."""
    session_registry = MagicMock()
    session_registry.get_session_owner = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._get_shared_session_registry", lambda: session_registry)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    allowed, status, detail = await tr._validate_streamable_session_access(
        mcp_session_id="sess-abc",
        user_context={"email": "dev@example.com", "is_admin": False, "is_authenticated": True},
        rpc_method="ping",
    )
    assert allowed is False
    assert status == 403
    assert "unavailable" in detail.lower()


@pytest.mark.asyncio
async def test_validate_session_access_session_exists_exception(monkeypatch):
    """session_exists exception should return 403 (line 697)."""
    session_registry = MagicMock()
    session_registry.get_session_owner = AsyncMock(return_value=None)
    session_registry.session_exists = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._get_shared_session_registry", lambda: session_registry)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    allowed, status, detail = await tr._validate_streamable_session_access(
        mcp_session_id="sess-xyz",
        user_context={"email": "dev@example.com", "is_admin": False, "is_authenticated": True},
        rpc_method="tools/call",
    )
    assert allowed is False
    assert status == 403
    assert "unavailable" in detail.lower()


# ---------------------------------------------------------------------------
# Session owner mismatch warning (line 2529)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_owner_mismatch_logs_warning(monkeypatch, caplog):
    """When _claim_streamable_session_owner returns a different owner, a warning is logged (line 2529)."""
    # Standard
    import logging

    # _claim returns a DIFFERENT owner than the requester (non-admin)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._claim_streamable_session_owner", AsyncMock(return_value="actual_owner@example.com"))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send):
            send_func = send
            # Emit a session ID in the response to trigger the ownership code
            await send_func(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"mcp-session-id", b"new-session-id")],
                }
            )
            await send_func({"type": "http.response.body", "body": b"ok"})

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    send, _messages = _make_send_collector()
    scope = _make_scope("/mcp", method="POST", headers=[])

    mock_pool = MagicMock()
    mock_pool.register_pool_session_owner = AsyncMock()

    with patch("mcpgateway.services.mcp_session_pool.get_mcp_session_pool", return_value=mock_pool):
        with patch("mcpgateway.services.mcp_session_pool.WORKER_ID", "worker-1"):
            token = tr.user_context_var.set(
                {
                    "email": "requester@example.com",
                    "teams": ["t1"],
                    "is_authenticated": True,
                    "is_admin": False,
                }
            )
            try:
                with caplog.at_level(logging.WARNING, logger="mcpgateway.transports.streamablehttp_transport"):
                    await wrapper.handle_streamable_http(scope, _make_receive(b""), send)
            finally:
                tr.user_context_var.reset(token)

    await wrapper.shutdown()
    assert any("Session owner mismatch" in msg for msg in caplog.messages)


# ---------------------------------------------------------------------------
# streamable_http_auth: SQLAlchemyError returns 503
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streamable_http_auth_sqlalchemy_error_returns_503(monkeypatch):
    """SQLAlchemyError during JWT team resolution returns 503."""
    # Third-Party
    from sqlalchemy.exc import SQLAlchemyError

    async def fake_verify(token):
        return {
            "sub": "user@example.com",
            "email": "user@example.com",
            "teams": ["team-1"],
            "is_admin": False,
        }

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", True)

    # normalize_token_teams is imported locally from mcpgateway.auth
    monkeypatch.setattr(
        "mcpgateway.auth.normalize_token_teams",
        MagicMock(side_effect=SQLAlchemyError("DB connection lost")),
    )

    scope = _make_scope(
        "/servers/1/mcp",
        headers=[(b"authorization", b"Bearer good-token")],
    )
    sent = []

    async def send(msg):
        sent.append(msg)

    result = await streamable_http_auth(scope, None, send)

    assert result is False
    assert sent and sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 503


@pytest.mark.asyncio
async def test_streamable_http_auth_unexpected_exception_returns_401(monkeypatch):
    """Unexpected (non-HTTPException, non-SQLAlchemy) error during JWT auth returns 401."""

    async def fake_verify(token):
        raise RuntimeError("Something completely unexpected")

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", True)

    scope = _make_scope(
        "/servers/1/mcp",
        headers=[(b"authorization", b"Bearer bad-token")],
    )
    sent = []

    async def send(msg):
        sent.append(msg)

    result = await streamable_http_auth(scope, None, send)

    assert result is False
    assert sent and sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 401


# ── Token scope enforcement tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_call_tool_denied_by_token_scope(monkeypatch):
    """Token with tools.read but not tools.execute should be denied call_tool via scope check."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service

    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default",
        AsyncMock(
            return_value=(
                "server-1",
                {},
                {"email": "dev@example.com", "teams": ["team-1"], "is_admin": False, "is_authenticated": True, "scoped_permissions": ["servers.use", "tools.read"]},
            )
        ),
    )
    # RBAC would allow, but token scope should deny
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._check_streamable_permission", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", False)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda _headers: None)
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock())

    with pytest.raises(PermissionError, match="Access denied"):
        await call_tool("mytool", {"foo": "bar"})

    tool_service.invoke_tool.assert_not_called()


@pytest.mark.asyncio
async def test_call_tool_allowed_by_token_scope(monkeypatch):
    """Token with tools.execute in scope should be allowed."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service

    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default",
        AsyncMock(
            return_value=(
                "server-1",
                {},
                {"email": "dev@example.com", "teams": ["team-1"], "is_admin": False, "is_authenticated": True, "scoped_permissions": ["servers.use", "tools.execute"]},
            )
        ),
    )
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._check_streamable_permission", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", False)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda _headers: None)
    # Third-Party
    from mcp import types as mcp_types

    tool_result = MagicMock()
    tool_result.content = [mcp_types.TextContent(type="text", text="ok")]
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=tool_result))

    await call_tool("mytool", {"foo": "bar"})
    tool_service.invoke_tool.assert_called_once()


@pytest.mark.asyncio
async def test_call_tool_allowed_with_empty_scoped_permissions(monkeypatch):
    """Token with no scoped permissions (defer to RBAC) should be allowed if RBAC passes."""
    # Third-Party
    from mcp import types as mcp_types

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service

    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default",
        AsyncMock(
            return_value=(
                "server-1",
                {},
                {"email": "dev@example.com", "teams": ["team-1"], "is_admin": False, "is_authenticated": True},
            )
        ),
    )
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._check_streamable_permission", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", False)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda _headers: None)
    tool_result = MagicMock()
    tool_result.content = [mcp_types.TextContent(type="text", text="ok")]
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=tool_result))

    await call_tool("mytool", {"foo": "bar"})
    tool_service.invoke_tool.assert_called_once()


# ---------------------------------------------------------------------------
# Regression tests for context propagation and RBAC fixes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_should_enforce_streamable_rbac_false_for_unauthenticated():
    """_should_enforce_streamable_rbac must return False when is_authenticated is False.

    Regression: the original implementation checked key existence
    (``"is_authenticated" in user_context``) instead of the value, so a
    context with ``is_authenticated: False`` would incorrectly trigger RBAC.
    """
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _should_enforce_streamable_rbac

    # Unauthenticated context (set by middleware for public access)
    assert _should_enforce_streamable_rbac({"email": None, "teams": [], "is_authenticated": False, "is_admin": False}) is False

    # Authenticated context — RBAC should be enforced
    assert _should_enforce_streamable_rbac({"email": "user@example.com", "teams": ["t1"], "is_authenticated": True, "is_admin": False}) is True

    # Empty dict (default ContextVar value) — no RBAC
    assert _should_enforce_streamable_rbac({}) is False

    # None — no RBAC
    assert _should_enforce_streamable_rbac(None) is False


@pytest.mark.asyncio
async def test_get_request_context_reads_scope_context(monkeypatch):
    """_get_request_context_or_default reads _mcpgateway_context from ASGI scope.

    Regression: ContextVars set by the middleware are lost when the MCP SDK
    dispatches handlers in tasks spawned from its startup-time task group.
    The fix stores context on scope["_mcpgateway_context"] before SDK dispatch
    and reads it back in _get_request_context_or_default.
    """
    # Standard
    from unittest.mock import PropertyMock

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _get_request_context_or_default, mcp_app, server_id_var

    # Ensure ContextVars are at defaults (simulating SDK task context)
    token = server_id_var.set("default_server_id")

    injected_user_context = {"email": "pub@example.com", "teams": [], "is_authenticated": True, "is_admin": False}
    injected_headers = {"authorization": "Bearer tok123"}
    injected_server_id = "abc123def456"

    mock_scope = {
        _MCPGATEWAY_CONTEXT_KEY: {
            "server_id": injected_server_id,
            "request_headers": injected_headers,
            "user_context": injected_user_context,
        }
    }

    mock_request = MagicMock()
    mock_request.scope = mock_scope

    mock_ctx = MagicMock()
    mock_ctx.request = mock_request

    try:
        with patch.object(type(mcp_app), "request_context", new_callable=PropertyMock, return_value=mock_ctx):
            sid, headers, user = await _get_request_context_or_default()

            assert sid == injected_server_id
            assert headers == injected_headers
            assert user == injected_user_context
    finally:
        server_id_var.reset(token)


@pytest.mark.asyncio
async def test_get_request_context_scope_fallback_to_reauth(monkeypatch):
    """When _mcpgateway_context is absent from scope, falls back to re-authentication."""
    # Standard
    from unittest.mock import PropertyMock

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _get_request_context_or_default, mcp_app, server_id_var

    token = server_id_var.set("default_server_id")

    valid_hex_id = "abc123def456"

    mock_request = MagicMock()
    mock_request.scope = {}  # No _mcpgateway_context
    mock_request.url.path = f"/servers/{valid_hex_id}/mcp"
    mock_request.headers = {"authorization": "Bearer token"}
    mock_request.cookies = {}

    mock_ctx = MagicMock()
    mock_ctx.request = mock_request

    raw_jwt = {"sub": "test_user@example.com", "token_use": "api", "teams": ["team-1"]}
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.require_auth_header_first", AsyncMock(return_value=raw_jwt))

    normalized = {"email": "test_user@example.com", "teams": ["team-1"], "is_admin": False, "is_authenticated": True}
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._normalize_jwt_payload", AsyncMock(side_effect=lambda payload: normalized))

    try:
        with patch.object(type(mcp_app), "request_context", new_callable=PropertyMock, return_value=mock_ctx):
            sid, headers, user = await _get_request_context_or_default()

            assert sid == valid_hex_id
            assert user == normalized
    finally:
        server_id_var.reset(token)


@pytest.mark.asyncio
async def test_should_enforce_streamable_rbac_rejects_truthy_non_bool():
    """_should_enforce_streamable_rbac must only trigger on ``True``, not on truthy values.

    Regression: using ``is True`` identity comparison prevents objects like
    non-empty strings or integers from accidentally enabling RBAC enforcement.
    """
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _should_enforce_streamable_rbac

    # Truthy non-bool values must NOT trigger RBAC
    assert _should_enforce_streamable_rbac({"is_authenticated": 1}) is False
    assert _should_enforce_streamable_rbac({"is_authenticated": "yes"}) is False

    # Only explicit True triggers RBAC
    assert _should_enforce_streamable_rbac({"is_authenticated": True}) is True


@pytest.mark.asyncio
async def test_get_request_context_scope_null_server_id_falls_back(monkeypatch):
    """When _mcpgateway_context has server_id=None, falls back to the ContextVar default."""
    # Standard
    from unittest.mock import PropertyMock

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _get_request_context_or_default, mcp_app, server_id_var

    token = server_id_var.set("default_server_id")

    injected_user_context = {"email": "u@example.com", "teams": [], "is_authenticated": True, "is_admin": False}

    mock_scope = {
        _MCPGATEWAY_CONTEXT_KEY: {
            "server_id": None,  # Null server_id — should fall back to s_id
            "request_headers": {"x-custom": "val"},
            "user_context": injected_user_context,
        }
    }

    mock_request = MagicMock()
    mock_request.scope = mock_scope
    mock_ctx = MagicMock()
    mock_ctx.request = mock_request

    try:
        with patch.object(type(mcp_app), "request_context", new_callable=PropertyMock, return_value=mock_ctx):
            sid, headers, user = await _get_request_context_or_default()

            # server_id falls back to s_id ("default_server_id") because gw_ctx value is None
            assert sid == "default_server_id"
            assert headers == {"x-custom": "val"}
            assert user == injected_user_context
    finally:
        server_id_var.reset(token)


@pytest.mark.asyncio
async def test_get_request_context_scope_non_dict_mcpgateway_context_skipped(monkeypatch):
    """When _mcpgateway_context is not a dict, scope path is skipped and falls to re-auth."""
    # Standard
    from unittest.mock import PropertyMock

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _get_request_context_or_default, mcp_app, server_id_var

    token = server_id_var.set("default_server_id")

    mock_request = MagicMock()
    mock_request.scope = {_MCPGATEWAY_CONTEXT_KEY: "not-a-dict"}  # Invalid type
    mock_request.url.path = "/mcp"
    mock_request.headers = {}
    mock_request.cookies = {}

    mock_ctx = MagicMock()
    mock_ctx.request = mock_request

    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport.require_auth_header_first",
        AsyncMock(return_value="anonymous"),
    )

    try:
        with patch.object(type(mcp_app), "request_context", new_callable=PropertyMock, return_value=mock_ctx):
            sid, _headers, user = await _get_request_context_or_default()

            # Fell through to re-auth fallback → anonymous → empty context
            assert sid == "default_server_id"
            assert user == {}
    finally:
        server_id_var.reset(token)


@pytest.mark.asyncio
async def test_get_request_context_scope_request_none_returns_defaults():
    """When request_context.request is None in the scope-reading step, returns ContextVar defaults."""
    # Standard
    from unittest.mock import PropertyMock

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _get_request_context_or_default, mcp_app, server_id_var, user_context_var

    sid_token = server_id_var.set("default_server_id")
    uc_token = user_context_var.set({})

    mock_ctx = MagicMock()
    mock_ctx.request = None  # No request available

    try:
        with patch.object(type(mcp_app), "request_context", new_callable=PropertyMock, return_value=mock_ctx):
            sid, _headers, user = await _get_request_context_or_default()

            # request is None → scope path skipped → falls to re-auth fallback
            # re-auth fallback also sees request=None → logs warning and returns defaults
            assert sid == "default_server_id"
            assert user == {}
    finally:
        server_id_var.reset(sid_token)
        user_context_var.reset(uc_token)


@pytest.mark.asyncio
async def test_get_request_context_scope_lookup_error_returns_defaults():
    """LookupError in scope-reading step returns ContextVar defaults."""
    # Standard
    from unittest.mock import PropertyMock

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _get_request_context_or_default, mcp_app, server_id_var, user_context_var

    sid_token = server_id_var.set("default_server_id")
    uc_token = user_context_var.set({})

    try:
        with patch.object(
            type(mcp_app),
            "request_context",
            new_callable=PropertyMock,
            side_effect=LookupError("no active context"),
        ):
            sid, _headers, user = await _get_request_context_or_default()

            assert sid == "default_server_id"
            assert user == {}
    finally:
        server_id_var.reset(sid_token)
        user_context_var.reset(uc_token)


@pytest.mark.asyncio
async def test_get_request_context_scope_generic_exception_falls_through(monkeypatch, caplog):
    """Generic exception in scope-reading step logs debug and falls through to re-auth."""
    # Standard
    import logging
    from unittest.mock import PropertyMock

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _get_request_context_or_default, mcp_app, server_id_var

    token = server_id_var.set("default_server_id")

    mock_ctx = MagicMock()
    mock_request = MagicMock()
    # First access (scope-reading step) raises generic error
    type(mock_request).scope = PropertyMock(side_effect=RuntimeError("scope broken"))
    mock_ctx.request = mock_request

    # Re-auth fallback: need a fresh mock_ctx that works
    call_count = 0

    def get_request_context():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: scope-reading step — request.scope raises
            return mock_ctx
        # Second call: re-auth fallback
        fallback_request = MagicMock()
        fallback_request.url.path = "/mcp"
        fallback_request.headers = {}
        fallback_request.cookies = {}
        fallback_ctx = MagicMock()
        fallback_ctx.request = fallback_request
        return fallback_ctx

    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport.require_auth_header_first",
        AsyncMock(return_value="anonymous"),
    )

    try:
        with patch.object(
            type(mcp_app),
            "request_context",
            new_callable=PropertyMock,
            side_effect=get_request_context,
        ):
            with caplog.at_level(logging.DEBUG, logger="mcpgateway.transports.streamablehttp_transport"):
                sid, _headers, user = await _get_request_context_or_default()

                assert sid == "default_server_id"
                assert user == {}
                assert "Failed to read _mcpgateway_context from scope" in caplog.text
    finally:
        server_id_var.reset(token)


def _scoped_user_context(scoped_permissions):
    """Build an authenticated user context with scoped permissions for testing."""
    return {
        "email": "dev@example.com",
        "teams": ["team-1"],
        "is_admin": False,
        "is_authenticated": True,
        "scoped_permissions": scoped_permissions,
    }


def _patch_request_context(monkeypatch, user_context):
    """Patch _get_request_context_or_default with given user context."""
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default",
        AsyncMock(return_value=("server-1", {}, user_context)),
    )


@pytest.mark.asyncio
async def test_list_tools_denied_by_token_scope(monkeypatch):
    """Token without tools.read should be denied list_tools."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_tools

    _patch_request_context(monkeypatch, _scoped_user_context(["servers.use"]))

    with pytest.raises(PermissionError, match="Access denied"):
        await list_tools()


@pytest.mark.asyncio
async def test_list_resources_denied_by_token_scope(monkeypatch):
    """Token without resources.read should be denied list_resources."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_resources

    _patch_request_context(monkeypatch, _scoped_user_context(["servers.use"]))

    with pytest.raises(PermissionError, match="Access denied"):
        await list_resources()


@pytest.mark.asyncio
async def test_read_resource_denied_by_token_scope(monkeypatch):
    """Token without resources.read should be denied read_resource."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import read_resource

    _patch_request_context(monkeypatch, _scoped_user_context(["servers.use"]))

    with pytest.raises(PermissionError, match="Access denied"):
        await read_resource("resource://test")


@pytest.mark.asyncio
async def test_list_prompts_denied_by_token_scope(monkeypatch):
    """Token without prompts.read should be denied list_prompts."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_prompts

    _patch_request_context(monkeypatch, _scoped_user_context(["servers.use"]))

    with pytest.raises(PermissionError, match="Access denied"):
        await list_prompts()


@pytest.mark.asyncio
async def test_get_prompt_denied_by_token_scope(monkeypatch):
    """Token without prompts.read should be denied get_prompt."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import get_prompt

    _patch_request_context(monkeypatch, _scoped_user_context(["servers.use"]))

    with pytest.raises(PermissionError, match="Access denied"):
        await get_prompt("test-prompt")


@pytest.mark.asyncio
async def test_list_resource_templates_denied_by_token_scope(monkeypatch):
    """Token without resources.read should be denied list_resource_templates."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_resource_templates

    _patch_request_context(monkeypatch, _scoped_user_context(["servers.use"]))

    with pytest.raises(PermissionError, match="Access denied"):
        await list_resource_templates()


@pytest.mark.asyncio
async def test_call_tool_allowed_with_wildcard_scoped_permissions(monkeypatch):
    """Token with wildcard scoped permissions should pass scope check."""
    # Third-Party
    from mcp import types as mcp_types

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service

    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default",
        AsyncMock(
            return_value=(
                "server-1",
                {},
                {"email": "dev@example.com", "teams": ["team-1"], "is_admin": False, "is_authenticated": True, "scoped_permissions": ["*"]},
            )
        ),
    )
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._check_streamable_permission", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", False)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda _headers: None)
    tool_result = MagicMock()
    tool_result.content = [mcp_types.TextContent(type="text", text="ok")]
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=tool_result))

    await call_tool("mytool", {"foo": "bar"})
    tool_service.invoke_tool.assert_called_once()


@pytest.mark.asyncio
async def test_normalize_jwt_payload_with_scoped_permissions(monkeypatch):
    """API token with scopes.permissions should include scoped_permissions in context."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _normalize_jwt_payload

    monkeypatch.setattr("mcpgateway.auth.normalize_token_teams", lambda payload: ["team-a"])

    raw = {
        "sub": "user@example.com",
        "token_use": "api",
        "teams": ["team-a"],
        "scopes": {"permissions": ["tools.read", "servers.use"]},
    }
    result = await _normalize_jwt_payload(raw)
    assert result["scoped_permissions"] == ["tools.read", "servers.use"]
    assert result["is_authenticated"] is True


@pytest.mark.asyncio
async def test_set_logging_level_denied_by_token_scope(monkeypatch):
    """Token without servers.use should be denied set_logging_level."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import set_logging_level

    _patch_request_context(monkeypatch, _scoped_user_context(["tools.read"]))

    with pytest.raises(PermissionError, match="Access denied"):
        await set_logging_level("error")


@pytest.mark.asyncio
async def test_auth_jwt_scoped_permissions_in_user_context(monkeypatch):
    """_auth_jwt should propagate scopes.permissions into user_context_var."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import (
        _StreamableHttpAuthHandler,
        user_context_var,
    )

    jwt_payload = {
        "sub": "user@example.com",
        "is_admin": True,
        "token_use": "api",
        "scopes": {"permissions": ["tools.read", "tools.execute", "servers.use"]},
    }

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.verify_credentials", AsyncMock(return_value=jwt_payload))
    # Admin with normalize_token_teams returning None bypasses team membership check
    monkeypatch.setattr("mcpgateway.auth.normalize_token_teams", lambda payload: None)

    handler = _StreamableHttpAuthHandler(
        scope={"type": "http", "headers": []},
        receive=AsyncMock(),
        send=AsyncMock(),
    )

    result = await handler._auth_jwt(token="fake-token")
    assert result is True

    ctx = user_context_var.get()
    assert ctx["scoped_permissions"] == ["tools.read", "tools.execute", "servers.use"]
    assert ctx["email"] == "user@example.com"
    assert ctx["auth_method"] == "jwt"


@pytest.mark.asyncio
async def test_auth_jwt_uses_cached_auth_context_and_cached_teams(monkeypatch):
    """Cached auth context and cached teams should avoid fallback lookups and preserve scoped server ids."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _StreamableHttpAuthHandler, user_context_var

    jwt_payload = {
        "sub": "user@example.com",
        "is_admin": False,
        "token_use": "session",
        "scopes": {"server_id": "srv-1"},
    }
    cached_ctx = MagicMock()
    cached_ctx.is_token_revoked = False
    cached_ctx.user = {"is_active": True, "is_admin": True}
    auth_cache = MagicMock()
    auth_cache.get_auth_context = AsyncMock(return_value=cached_ctx)
    auth_cache.get_user_teams = AsyncMock(return_value=["team-a"])
    auth_cache.get_team_membership_valid_sync = MagicMock(return_value=True)

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.verify_credentials", AsyncMock(return_value=jwt_payload))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.auth_cache_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.auth_cache_batch_queries", False)
    monkeypatch.setattr("mcpgateway.cache.auth_cache.get_auth_cache", lambda: auth_cache)

    handler = _StreamableHttpAuthHandler(scope={"type": "http", "headers": []}, receive=AsyncMock(), send=AsyncMock())

    result = await handler._auth_jwt(token="fake-token")

    assert result is True
    ctx = user_context_var.get()
    assert ctx["teams"] == ["team-a"]
    assert ctx["permission_is_admin"] is True
    assert ctx["scoped_server_id"] == "srv-1"
    assert ctx["auth_method"] == "jwt"


@pytest.mark.asyncio
async def test_auth_jwt_falls_back_after_cache_errors_and_tolerates_cache_set_failure(monkeypatch):
    """Fallback auth flow should survive cache lookup/set failures and revocation-check exceptions."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _StreamableHttpAuthHandler, user_context_var

    jwt_payload = {
        "sub": "user@example.com",
        "is_admin": False,
        "token_use": "session",
    }
    user_record = MagicMock()
    user_record.email = "user@example.com"
    user_record.password_hash = "hash"
    user_record.full_name = "User"
    user_record.is_admin = True
    user_record.is_active = True
    user_record.auth_provider = "local"
    user_record.password_change_required = False
    user_record.email_verified_at = None
    user_record.created_at = None
    user_record.updated_at = None

    auth_cache = MagicMock()
    auth_cache.get_auth_context = AsyncMock(side_effect=RuntimeError("cache down"))
    auth_cache.set_auth_context = AsyncMock(side_effect=RuntimeError("cache set failed"))
    auth_cache.set_user_teams = AsyncMock(return_value=None)
    auth_cache.get_team_membership_valid_sync = MagicMock(return_value=True)

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.verify_credentials", AsyncMock(return_value=jwt_payload))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.auth_cache_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.auth_cache_batch_queries", False)
    monkeypatch.setattr("mcpgateway.cache.auth_cache.get_auth_cache", lambda: auth_cache)
    monkeypatch.setattr("mcpgateway.auth._check_token_revoked_sync", MagicMock(side_effect=RuntimeError("revocation down")))
    monkeypatch.setattr("mcpgateway.auth._get_user_by_email_sync", MagicMock(return_value=user_record))
    monkeypatch.setattr("mcpgateway.auth.resolve_session_teams", AsyncMock(return_value=["team-a"]))

    handler = _StreamableHttpAuthHandler(scope={"type": "http", "headers": []}, receive=AsyncMock(), send=AsyncMock())

    result = await handler._auth_jwt(token="fake-token")

    assert result is True
    ctx = user_context_var.get()
    assert ctx["teams"] == ["team-a"]
    assert ctx["permission_is_admin"] is True


@pytest.mark.asyncio
async def test_auth_jwt_uses_batched_auth_context_and_caches_team_list(monkeypatch):
    """Batched auth lookups should populate context and tolerate team-cache write failures."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _StreamableHttpAuthHandler, user_context_var

    jwt_payload = {
        "sub": "user@example.com",
        "is_admin": False,
        "token_use": "session",
    }
    batched_auth_ctx = {
        "user": {"is_active": True, "is_admin": True},
        "personal_team_id": None,
        "is_token_revoked": False,
        "team_ids": ["team-a"],
    }
    auth_cache = MagicMock()
    auth_cache.get_auth_context = AsyncMock(return_value=None)
    auth_cache.set_auth_context = AsyncMock(return_value=None)
    auth_cache.set_user_teams = AsyncMock(side_effect=RuntimeError("team cache down"))
    auth_cache.get_team_membership_valid_sync = MagicMock(return_value=True)

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.verify_credentials", AsyncMock(return_value=jwt_payload))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.auth_cache_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.auth_cache_batch_queries", True)
    monkeypatch.setattr("mcpgateway.cache.auth_cache.get_auth_cache", lambda: auth_cache)
    monkeypatch.setattr("mcpgateway.auth._get_auth_context_batched_sync", MagicMock(return_value=batched_auth_ctx))

    handler = _StreamableHttpAuthHandler(scope={"type": "http", "headers": []}, receive=AsyncMock(), send=AsyncMock())

    result = await handler._auth_jwt(token="fake-token")

    assert result is True
    ctx = user_context_var.get()
    assert ctx["teams"] == ["team-a"]
    assert ctx["permission_is_admin"] is True


@pytest.mark.asyncio
async def test_auth_jwt_cached_context_requires_user_when_db_user_missing(monkeypatch):
    """Cached auth contexts without a DB user should reject when REQUIRE_USER_IN_DB is enabled."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _StreamableHttpAuthHandler

    jwt_payload = {"sub": "user@example.com", "is_admin": False, "token_use": "session"}
    cached_ctx = MagicMock()
    cached_ctx.is_token_revoked = False
    cached_ctx.user = None
    auth_cache = MagicMock()
    auth_cache.get_auth_context = AsyncMock(return_value=cached_ctx)

    send_error = AsyncMock(return_value=False)
    monkeypatch.setattr(_StreamableHttpAuthHandler, "_send_error", send_error)
    handler = _StreamableHttpAuthHandler(scope={"type": "http", "headers": []}, receive=AsyncMock(), send=AsyncMock())

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.verify_credentials", AsyncMock(return_value=jwt_payload))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.auth_cache_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.auth_cache_batch_queries", False)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.require_user_in_db", True)
    monkeypatch.setattr("mcpgateway.cache.auth_cache.get_auth_cache", lambda: auth_cache)

    assert await handler._auth_jwt(token="fake-token") is False


@pytest.mark.asyncio
async def test_auth_jwt_returns_invalid_credentials_when_cache_lookup_raises_http_exception(monkeypatch):
    """HTTPException from auth cache lookup should be surfaced as invalid credentials."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _StreamableHttpAuthHandler

    jwt_payload = {"sub": "user@example.com", "is_admin": False, "token_use": "session"}
    auth_cache = MagicMock()
    auth_cache.get_auth_context = AsyncMock(side_effect=HTTPException(status_code=401, detail="bad"))

    send_error = AsyncMock(return_value=False)
    monkeypatch.setattr(_StreamableHttpAuthHandler, "_send_error", send_error)
    handler = _StreamableHttpAuthHandler(scope={"type": "http", "headers": []}, receive=AsyncMock(), send=AsyncMock())

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.verify_credentials", AsyncMock(return_value=jwt_payload))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.auth_cache_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.auth_cache_batch_queries", False)
    monkeypatch.setattr("mcpgateway.cache.auth_cache.get_auth_cache", lambda: auth_cache)

    assert await handler._auth_jwt(token="fake-token") is False
    send_error.assert_awaited_once()


@pytest.mark.asyncio
async def test_auth_jwt_batched_context_requires_user_when_db_user_missing(monkeypatch):
    """Batched auth lookups without a DB user should reject when REQUIRE_USER_IN_DB is enabled."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _StreamableHttpAuthHandler

    jwt_payload = {"sub": "user@example.com", "is_admin": False, "token_use": "session"}
    auth_cache = MagicMock()
    auth_cache.get_auth_context = AsyncMock(return_value=None)

    send_error = AsyncMock(return_value=False)
    monkeypatch.setattr(_StreamableHttpAuthHandler, "_send_error", send_error)
    handler = _StreamableHttpAuthHandler(scope={"type": "http", "headers": []}, receive=AsyncMock(), send=AsyncMock())

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.verify_credentials", AsyncMock(return_value=jwt_payload))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.auth_cache_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.auth_cache_batch_queries", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.require_user_in_db", True)
    monkeypatch.setattr("mcpgateway.cache.auth_cache.get_auth_cache", lambda: auth_cache)
    monkeypatch.setattr("mcpgateway.auth._get_auth_context_batched_sync", MagicMock(return_value={"user": None, "team_ids": [], "is_token_revoked": False}))

    assert await handler._auth_jwt(token="fake-token") is False


@pytest.mark.asyncio
async def test_auth_jwt_records_batch_team_cache_hit_on_success(monkeypatch):
    """Successful batched team caching should preserve the resolved team list."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _StreamableHttpAuthHandler, user_context_var

    jwt_payload = {"sub": "user@example.com", "is_admin": False, "token_use": "session"}
    auth_cache = MagicMock()
    auth_cache.get_auth_context = AsyncMock(return_value=None)
    auth_cache.set_auth_context = AsyncMock(return_value=None)
    auth_cache.set_user_teams = AsyncMock(return_value=None)
    auth_cache.get_team_membership_valid_sync = MagicMock(return_value=True)

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.verify_credentials", AsyncMock(return_value=jwt_payload))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.auth_cache_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.auth_cache_batch_queries", True)
    monkeypatch.setattr("mcpgateway.cache.auth_cache.get_auth_cache", lambda: auth_cache)
    monkeypatch.setattr("mcpgateway.auth._get_auth_context_batched_sync", MagicMock(return_value={"user": {"is_active": True, "is_admin": False}, "team_ids": ["team-a"], "is_token_revoked": False}))

    handler = _StreamableHttpAuthHandler(scope={"type": "http", "headers": []}, receive=AsyncMock(), send=AsyncMock())
    assert await handler._auth_jwt(token="fake-token") is True
    assert user_context_var.get()["teams"] == ["team-a"]


@pytest.mark.asyncio
async def test_auth_jwt_uses_batched_team_ids_when_auth_cache_is_disabled(monkeypatch):
    """Batched auth lookups should still populate session team context without the cache layer."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _StreamableHttpAuthHandler, user_context_var

    jwt_payload = {"sub": "user@example.com", "is_admin": False, "token_use": "session"}
    auth_cache = MagicMock()
    auth_cache.get_team_membership_valid_sync = MagicMock(return_value=True)

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.verify_credentials", AsyncMock(return_value=jwt_payload))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.auth_cache_enabled", False)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.auth_cache_batch_queries", True)
    monkeypatch.setattr("mcpgateway.cache.auth_cache.get_auth_cache", lambda: auth_cache)
    monkeypatch.setattr(
        "mcpgateway.auth._get_auth_context_batched_sync",
        MagicMock(return_value={"user": {"is_active": True, "is_admin": False}, "team_ids": ["team-b"], "is_token_revoked": False}),
    )

    handler = _StreamableHttpAuthHandler(scope={"type": "http", "headers": []}, receive=AsyncMock(), send=AsyncMock())

    assert await handler._auth_jwt(token="fake-token") is True
    assert user_context_var.get()["teams"] == ["team-b"]


@pytest.mark.asyncio
async def test_auth_jwt_returns_invalid_credentials_when_batched_lookup_raises_http_exception(monkeypatch):
    """HTTPException from the batched auth lookup should be surfaced as invalid credentials."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import _StreamableHttpAuthHandler

    jwt_payload = {"sub": "user@example.com", "is_admin": False, "token_use": "session"}
    auth_cache = MagicMock()
    auth_cache.get_auth_context = AsyncMock(return_value=None)

    send_error = AsyncMock(return_value=False)
    monkeypatch.setattr(_StreamableHttpAuthHandler, "_send_error", send_error)
    handler = _StreamableHttpAuthHandler(scope={"type": "http", "headers": []}, receive=AsyncMock(), send=AsyncMock())

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.verify_credentials", AsyncMock(return_value=jwt_payload))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.auth_cache_enabled", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.auth_cache_batch_queries", True)
    monkeypatch.setattr("mcpgateway.cache.auth_cache.get_auth_cache", lambda: auth_cache)
    monkeypatch.setattr("mcpgateway.auth._get_auth_context_batched_sync", MagicMock(side_effect=HTTPException(status_code=401, detail="bad")))

    assert await handler._auth_jwt(token="fake-token") is False
    send_error.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_denied_by_token_scope(monkeypatch):
    """Token without tools.read should be denied completion/complete."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import complete

    _patch_request_context(monkeypatch, _scoped_user_context(["servers.use"]))

    # Third-Party
    from mcp import types as mcp_types

    ref = mcp_types.PromptReference(type="ref/prompt", name="test-prompt")
    argument = mcp_types.CompleteRequest(
        method="completion/complete",
        params=mcp_types.CompleteRequestParams(ref=ref, argument=mcp_types.CompletionArgument(name="arg", value="val")),
    )

    with pytest.raises(PermissionError, match="Access denied"):
        await complete(ref, argument)


@pytest.mark.asyncio
async def test_validate_session_access_skips_rbac_for_unauthenticated(monkeypatch):
    """_validate_streamable_session_access skips RBAC for unauthenticated context.

    Regression: with the is_authenticated value-check fix, contexts with
    is_authenticated=False must cause the function to return (True, 200, "")
    without hitting session-ownership checks.
    """
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)

    # Should NOT reach session registry at all
    session_registry = MagicMock()
    session_registry.get_session_owner = AsyncMock(side_effect=AssertionError("should not be called"))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._get_shared_session_registry", lambda: session_registry)

    allowed, status, detail = await tr._validate_streamable_session_access(
        mcp_session_id="sess-abc",
        user_context={"email": None, "teams": [], "is_authenticated": False, "is_admin": False},
        rpc_method="tools/call",
    )
    assert allowed is True
    assert status == 200


@pytest.mark.asyncio
async def test_call_tool_skips_rbac_for_unauthenticated_context(monkeypatch):
    """call_tool must skip the tools.execute RBAC gate for unauthenticated contexts.

    Regression: _should_enforce_streamable_rbac now correctly returns False
    when is_authenticated is False, so the handler should not attempt
    permission checks at all.
    """
    # Third-Party
    from mcp import types as mcp_types

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service

    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default",
        AsyncMock(
            return_value=(
                "server-1",
                {},
                {"email": None, "teams": [], "is_authenticated": False, "is_admin": False},
            )
        ),
    )
    # _check_streamable_permission should NOT be called — if it is, fail the test
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._check_streamable_permission",
        AsyncMock(side_effect=AssertionError("RBAC check should not be reached for unauthenticated")),
    )
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._check_server_oauth_enforcement", AsyncMock())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", False)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda _headers: None)

    mock_result = MagicMock()
    mock_result.content = [mcp_types.TextContent(type="text", text="ok")]
    monkeypatch.setattr(tool_service, "invoke_tool", AsyncMock(return_value=mock_result))

    # Should succeed without hitting the permission check
    result = await call_tool("mytool", {"foo": "bar"})
    assert result is not None


@pytest.mark.asyncio
async def test_session_manager_wrapper_rbac_gate_denies_missing_servers_use(monkeypatch):
    """SessionManagerWrapper RBAC gate returns 403 Access denied when servers.use permission is absent."""
    # Standard
    from contextlib import asynccontextmanager
    import json

    class DummySessionManager:
        def __init__(self):
            self._server_instances = {}

        @asynccontextmanager
        async def run(self):
            yield self

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def handle_request(self, scope, receive, send_func):
            raise AssertionError("Session manager must not be reached after RBAC deny")

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._check_streamable_permission",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled",
        False,
    )

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    scope = _make_scope("/servers/123/mcp")
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        sent.append(msg)

    token = tr.user_context_var.set({"email": "user@example.com", "teams": ["team-1"], "is_admin": False, "is_authenticated": True})
    try:
        await wrapper.handle_streamable_http(scope, receive, send)
    finally:
        tr.user_context_var.reset(token)
        await wrapper.shutdown()

    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 403
    body = json.loads(sent[1]["body"])
    assert body["detail"] == "Access denied"


@pytest.mark.asyncio
async def test_handle_streamable_http_server_not_found_returns_404(monkeypatch):
    """Server-scoped Streamable HTTP requests return 404 when server ID doesn't exist in database."""
    # Standard
    from contextlib import asynccontextmanager

    # Third-Party
    import orjson

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import SessionManagerWrapper, user_context_var

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            raise AssertionError("Session manager must not be reached when server not found")

    dummy_manager = DummySessionManager()
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.StreamableHTTPSessionManager", lambda **kwargs: dummy_manager)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", False)

    # Mock permission check to pass (we want to test the server lookup failure)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._check_streamable_permission", AsyncMock(return_value=True))

    # Mock entity_exists to return False (server not found) — uses BaseService.entity_exists
    @asynccontextmanager
    async def mock_get_db():
        yield MagicMock()

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db)

    # First-Party
    from mcpgateway.services.server_service import ServerService

    monkeypatch.setattr(ServerService, "entity_exists", AsyncMock(return_value=False))

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    token = user_context_var.set({"email": "dev@example.com", "teams": ["team-1"], "is_admin": False, "is_authenticated": True})
    try:
        scope = _make_scope("/servers/abc123-def456-789/mcp", method="POST", headers=[(b"mcp-session-id", b"sess-1")])
        receive = _make_receive(orjson.dumps({"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": "1"}))
        send, messages = _make_send_collector()

        await wrapper.handle_streamable_http(scope, receive, send)

        # Verify 404 response
        assert len(messages) >= 2
        assert messages[0]["type"] == "http.response.start"
        assert messages[0]["status"] == 404
        assert messages[1]["type"] == "http.response.body"

        body = orjson.loads(messages[1]["body"])
        assert body["detail"] == "Server not found"
    finally:
        user_context_var.reset(token)


@pytest.mark.asyncio
async def test_handle_streamable_http_server_validation_db_error_returns_503(monkeypatch):
    """Server-scoped Streamable HTTP requests return 503 when database validation fails."""
    # Standard
    from contextlib import asynccontextmanager

    # Third-Party
    import orjson

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import SessionManagerWrapper, user_context_var

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, scope, receive, send_func):
            raise AssertionError("Session manager must not be reached when DB error occurs")

    dummy_manager = DummySessionManager()
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.StreamableHTTPSessionManager", lambda **kwargs: dummy_manager)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", False)

    # Mock permission check to pass (we want to test the DB error handling)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._check_streamable_permission", AsyncMock(return_value=True))

    # Mock entity_exists to raise (simulates database failure)
    @asynccontextmanager
    async def mock_get_db():
        yield MagicMock()

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db)

    # First-Party
    from mcpgateway.services.server_service import ServerService

    monkeypatch.setattr(ServerService, "entity_exists", AsyncMock(side_effect=Exception("Database connection failed")))

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    token = user_context_var.set({"email": "dev@example.com", "teams": ["team-1"], "is_admin": False, "is_authenticated": True})
    try:
        scope = _make_scope("/servers/abc123-def456-789/mcp", method="POST", headers=[(b"mcp-session-id", b"sess-1")])
        receive = _make_receive(orjson.dumps({"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": "1"}))
        send, messages = _make_send_collector()

        await wrapper.handle_streamable_http(scope, receive, send)

        # Verify 503 response
        assert len(messages) >= 2
        assert messages[0]["type"] == "http.response.start"
        assert messages[0]["status"] == 503
        assert messages[1]["type"] == "http.response.body"

        body = orjson.loads(messages[1]["body"])
        assert "Service unavailable" in body["detail"]
        assert "unable to verify server" in body["detail"]
    finally:
        user_context_var.reset(token)
        await wrapper.shutdown()


# ---------------------------------------------------------------------------
# Deny-path regression tests for #3891: invalid server IDs must not fall
# through to unscoped global behaviour.
# ---------------------------------------------------------------------------


class TestServerIdDenyPaths:
    """Regression tests ensuring invalid server IDs in /servers/{id}/mcp are
    rejected rather than silently falling through to global (unscoped) access.

    Covers:
    - Non-hex server IDs (e.g. "xyz")
    - URL-encoded special characters (e.g. "hello%20world")
    - Empty server ID segment (/servers//mcp)
    - Path traversal attempts (/../)
    - Hex-format IDs that don't exist in the database
    """

    @pytest.fixture(autouse=True)
    def _patch_infra(self, monkeypatch):
        """Common infrastructure patches for every test in this class."""
        # Standard
        from contextlib import asynccontextmanager

        monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", False)
        monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._check_streamable_permission", AsyncMock(return_value=True))

        @asynccontextmanager
        async def mock_get_db():
            yield MagicMock()

        monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db)

        # entity_exists returns False for every ID (no server exists)
        # First-Party
        from mcpgateway.services.server_service import ServerService

        monkeypatch.setattr(ServerService, "entity_exists", AsyncMock(return_value=False))

        class DummySessionManager:
            @asynccontextmanager
            async def run(self):
                yield self

            async def handle_request(self, scope, receive, send_func):
                raise AssertionError("Session manager must not be reached for invalid server IDs")

        monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())

    @staticmethod
    async def _run_request(path: str) -> tuple:
        """Fire a request at the given path and return (status, body_dict)."""
        # Third-Party
        import orjson

        # First-Party
        from mcpgateway.transports.streamablehttp_transport import SessionManagerWrapper, user_context_var

        wrapper = SessionManagerWrapper()
        await wrapper.initialize()

        token = user_context_var.set({"email": "dev@example.com", "teams": ["team-1"], "is_admin": False, "is_authenticated": True})
        try:
            scope = _make_scope(path, method="POST", headers=[(b"mcp-session-id", b"sess-1")])
            receive = _make_receive(orjson.dumps({"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": "1"}))
            send_fn, messages = _make_send_collector()

            await wrapper.handle_streamable_http(scope, receive, send_fn)

            assert len(messages) >= 2, f"Expected at least 2 ASGI messages, got {len(messages)}"
            status = messages[0]["status"]
            body = orjson.loads(messages[1]["body"])
            return status, body
        finally:
            user_context_var.reset(token)
            await wrapper.shutdown()

    # --- Non-hex server IDs (primary attack vector from #3891) ---

    @pytest.mark.asyncio
    async def test_non_hex_server_id_xyz_returns_404(self):
        """Non-hex server ID 'xyz' must return 404, not all tools."""
        status, body = await self._run_request("/servers/xyz/mcp")
        assert status == 404
        assert "not found" in body["detail"].lower() or "invalid" in body["detail"].lower()

    @pytest.mark.asyncio
    async def test_non_hex_server_id_with_letters_returns_404(self):
        """Server ID containing non-hex letters (g-z) must return 404."""
        status, body = await self._run_request("/servers/my-server-name/mcp")
        assert status == 404

    @pytest.mark.asyncio
    async def test_url_encoded_special_chars_returns_404(self):
        """URL-encoded special characters in server ID must return 404."""
        status, body = await self._run_request("/servers/hello%20world/mcp")
        assert status == 404

    # --- Empty / malformed server ID ---

    @pytest.mark.asyncio
    async def test_empty_server_id_returns_404(self):
        """Empty server ID segment (/servers//mcp) must return 404."""
        status, body = await self._run_request("/servers//mcp")
        assert status == 404

    # --- Path traversal attempts ---

    @pytest.mark.asyncio
    async def test_path_traversal_returns_404(self):
        """Path traversal in server ID must return 404."""
        status, body = await self._run_request("/servers/../servers/xyz/mcp")
        assert status == 404

    # --- Hex-format IDs that don't exist in DB ---

    @pytest.mark.asyncio
    async def test_hex_nonexistent_server_deadbeef_returns_404(self):
        """Hex-format server ID not in database must return 404."""
        status, body = await self._run_request("/servers/deadbeef/mcp")
        assert status == 404
        assert body["detail"] == "Server not found"

    @pytest.mark.asyncio
    async def test_hex_nonexistent_server_all_zeros_returns_404(self):
        """All-zero UUID-format server ID not in database must return 404."""
        status, body = await self._run_request("/servers/00000000-0000-0000-0000-000000000000/mcp")
        assert status == 404
        assert body["detail"] == "Server not found"

    @pytest.mark.asyncio
    async def test_uppercase_hex_nonexistent_returns_404(self):
        """Uppercase hex server ID not in database must return 404."""
        status, body = await self._run_request("/servers/AABB/mcp")
        assert status == 404
        assert body["detail"] == "Server not found"


@pytest.mark.asyncio
async def test_auth_no_token_sets_anonymous_trace_context(monkeypatch):
    """Permissive MCP auth should label anonymous/public-only trace context."""
    # First-Party
    from mcpgateway.utils.trace_context import clear_trace_context, get_trace_auth_method, get_trace_team_scope, get_trace_user_email

    clear_trace_context()
    monkeypatch.setattr(tr.settings, "mcp_require_auth", False)

    scope = {"path": "/mcp"}
    handler = tr._StreamableHttpAuthHandler(scope, AsyncMock(), AsyncMock())

    allowed = await handler._auth_no_token(path="/mcp", bearer_header_supplied=False)

    assert allowed is True
    assert get_trace_user_email() is None
    assert get_trace_auth_method() == "anonymous"
    assert get_trace_team_scope() == "public"
    clear_trace_context()


@pytest.mark.asyncio
async def test_auth_jwt_sets_trace_context_for_session_token(monkeypatch):
    """JWT MCP auth should populate team-scoped trace context."""
    # First-Party
    from mcpgateway.utils.trace_context import clear_trace_context, get_trace_auth_method, get_trace_team_name, get_trace_team_scope, get_trace_user_email

    clear_trace_context()
    monkeypatch.setattr(tr.settings, "auth_cache_enabled", False)
    monkeypatch.setattr(tr.settings, "auth_cache_batch_queries", False)
    monkeypatch.setattr(tr.settings, "require_user_in_db", False)

    payload = {
        "sub": "stream@example.com",
        "token_use": "session",
        "user": {"auth_provider": "local"},
    }
    user_record = SimpleNamespace(is_admin=False, is_active=True)

    scope = {"path": "/mcp"}
    handler = tr._StreamableHttpAuthHandler(scope, AsyncMock(), AsyncMock())

    with (
        patch("mcpgateway.transports.streamablehttp_transport.verify_credentials", AsyncMock(return_value=payload)),
        patch("mcpgateway.auth._check_token_revoked_sync", return_value=False),
        patch("mcpgateway.auth._get_user_by_email_sync", return_value=user_record),
        patch("mcpgateway.auth._get_team_name_by_id_sync", return_value="Stream Team"),
        patch("mcpgateway.auth.resolve_session_teams", AsyncMock(return_value=["team-stream"])),
    ):
        allowed = await handler._auth_jwt(token="jwt")

    assert allowed is True
    assert get_trace_user_email() == "stream@example.com"
    assert get_trace_auth_method() == "jwt"
    assert get_trace_team_scope() == "team-stream"
    assert get_trace_team_name() == "Stream Team"
    clear_trace_context()


def test_maybe_open_initialize_span_returns_none_for_non_initialize():
    """Non-initialize JSON-RPC payloads should not create transport spans."""
    body = tr.orjson.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})

    span_cm = tr._maybe_open_initialize_span(body, mcp_session_id=None, server_id=None)

    assert span_cm is None


def test_maybe_open_initialize_span_builds_initialize_attributes(monkeypatch):
    """Initialize payloads should create the public MCP handshake span."""
    captured = {}

    class _SpanContext:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _fake_create_span(name, attributes):
        captured["name"] = name
        captured["attributes"] = attributes
        return _SpanContext()

    monkeypatch.setattr(tr, "create_span", _fake_create_span)
    body = tr.orjson.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-03-26"},
        }
    )

    span_cm = tr._maybe_open_initialize_span(body, mcp_session_id="session-123", server_id="server-456")

    assert span_cm is not None
    assert captured == {
        "name": "mcp.initialize",
        "attributes": {
            "mcp.protocol_version": "2025-03-26",
            "mcp.session_id": "session-123",
            "server.id": "server-456",
        },
    }


@pytest.mark.asyncio
async def test_handle_streamable_http_initialize_span_closes_cleanly(monkeypatch):
    """The public initialize span should exit cleanly after successful handling."""
    # Standard
    from contextlib import asynccontextmanager

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import SessionManagerWrapper, user_context_var

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, _scope, receive, send_func):
            await receive()
            await send_func({"type": "http.response.start", "status": 200, "headers": []})
            await send_func({"type": "http.response.body", "body": b"{}"})

    @asynccontextmanager
    async def mock_get_db():
        yield MagicMock()

    span_cm = MagicMock()
    span_cm.__enter__ = MagicMock(return_value=MagicMock())
    span_cm.__exit__ = MagicMock(return_value=False)

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._check_streamable_permission", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", False)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", False)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._maybe_open_initialize_span", lambda *_args, **_kwargs: span_cm)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    token = user_context_var.set({"email": "dev@example.com", "teams": ["team-1"], "is_admin": False, "is_authenticated": True})
    try:
        scope = _make_scope("/mcp", method="POST", headers=[(b"mcp-session-id", b"sess-1")])
        receive = _make_receive(
            tr.orjson.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-03-26"},
                }
            )
        )
        send, _messages = _make_send_collector()

        await wrapper.handle_streamable_http(scope, receive, send)
    finally:
        user_context_var.reset(token)
        await wrapper.shutdown()

    span_cm.__enter__.assert_called_once()
    span_cm.__exit__.assert_called_once()
    assert span_cm.__exit__.call_args.args[-3:] == (None, None, None)


@pytest.mark.asyncio
async def test_handle_streamable_http_initialize_span_exits_with_exception(monkeypatch):
    """The public initialize span should receive the raised exception on exit."""
    # Standard
    from contextlib import asynccontextmanager

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import SessionManagerWrapper, user_context_var

    class DummySessionManager:
        @asynccontextmanager
        async def run(self):
            yield self

        async def handle_request(self, _scope, receive, _send_func):
            await receive()
            raise ValueError("initialize failed")

    @asynccontextmanager
    async def mock_get_db():
        yield MagicMock()

    span_cm = MagicMock()
    span_cm.__enter__ = MagicMock(return_value=MagicMock())
    span_cm.__exit__ = MagicMock(return_value=False)

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._check_streamable_permission", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", False)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", False)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._maybe_open_initialize_span", lambda *_args, **_kwargs: span_cm)

    wrapper = SessionManagerWrapper()
    await wrapper.initialize()

    token = user_context_var.set({"email": "dev@example.com", "teams": ["team-1"], "is_admin": False, "is_authenticated": True})
    try:
        scope = _make_scope("/mcp", method="POST", headers=[(b"mcp-session-id", b"sess-1")])
        receive = _make_receive(
            tr.orjson.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-03-26"},
                }
            )
        )
        send, _messages = _make_send_collector()

        with pytest.raises(ValueError, match="initialize failed"):
            await wrapper.handle_streamable_http(scope, receive, send)
    finally:
        user_context_var.reset(token)
        await wrapper.shutdown()

    span_cm.__enter__.assert_called_once()
    span_cm.__exit__.assert_called_once()
    exc_type, exc_val, _exc_tb = span_cm.__exit__.call_args.args[-3:]
    assert exc_type is ValueError
    assert isinstance(exc_val, ValueError)
    assert str(exc_val) == "initialize failed"


# --------------------------------------------------------------------------- #
# Security regression tests for _meta handling in direct-proxy (CWE-400/CWE-20)#
# --------------------------------------------------------------------------- #


class TestProxyReadResourceMetaInjection:
    """Tests for _proxy_read_resource_to_gateway meta injection (Finding 7 / CWE-20)."""

    @pytest.mark.asyncio
    async def test_model_dump_uses_by_alias_so_meta_is_not_dropped(self, monkeypatch):
        """_meta must survive the model_dump(by_alias=True)+model_validate round-trip (CWE-20).

        Regression for Finding 7: model_dump() without by_alias=True produces {"uri": ..., "meta": None}
        causing the alias key "_meta" not to be the primary key written. Using by_alias=True ensures
        the output dict has "_meta" as the field key, which is then correctly overwritten with the
        caller-supplied metadata before model_validate is called.
        """
        from mcp.types import ReadResourceRequestParams

        meta_data = {"trace_id": "abc", "request_id": "123"}

        # The fixed path: model_dump(by_alias=True) then overwrite _meta
        params = ReadResourceRequestParams(uri="file:///test.txt")
        dump_with_alias = params.model_dump(by_alias=True)

        # With by_alias=True the field appears under its alias "_meta" (not "meta")
        assert "_meta" in dump_with_alias

        # Overwrite with our metadata and validate
        dump_with_alias["_meta"] = meta_data
        validated = ReadResourceRequestParams.model_validate(dump_with_alias)
        assert validated.meta is not None
        # All injected keys must survive round-trip
        as_dict = validated.meta.model_dump()
        assert meta_data.items() <= as_dict.items()


class TestDirectProxyValidatesMeta:
    """Validate that the direct-proxy branch in read_resource applies CWE-400 guards (Finding 1)."""

    @pytest.mark.asyncio
    async def test_read_resource_direct_proxy_rejects_oversized_meta(self, monkeypatch):
        """meta_data must be validated before _proxy_read_resource_to_gateway is called (Finding 1 / CWE-400)."""
        from mcpgateway.common.validators import META_MAX_KEYS
        from mcpgateway.transports.streamablehttp_transport import _validate_meta_data

        oversized = {str(i): i for i in range(META_MAX_KEYS + 1)}
        with pytest.raises(ValueError, match="maximum key count"):
            _validate_meta_data(oversized)

    @pytest.mark.asyncio
    async def test_read_resource_direct_proxy_rejects_list_of_dicts_depth_bypass(self, monkeypatch):
        """List-of-dicts depth bypass must be caught before _proxy_read_resource_to_gateway (Finding 1/3 / CWE-400)."""
        from mcpgateway.transports.streamablehttp_transport import _validate_meta_data

        hidden_depth = {"k": [{"l2": {"l3": "x"}}]}
        with pytest.raises(ValueError, match="maximum nesting depth"):
            _validate_meta_data(hidden_depth)
