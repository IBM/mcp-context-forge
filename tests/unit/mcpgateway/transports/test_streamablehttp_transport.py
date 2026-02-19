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

    with caplog.at_level("WARNING"):
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
async def test_list_tools_with_server_id(monkeypatch):
    """Test list_tools returns tools for a server_id."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_tools, server_id_var, tool_service

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
    assert result[0].description == "desc"


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
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_tools, server_id_var, tool_service

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(tool_service, "list_server_tools", AsyncMock(side_effect=Exception("server fail!")))

    token = server_id_var.set("test-server-id")
    with caplog.at_level("ERROR"):
        result = await list_tools()
        assert result == []
        assert "Error listing tools:server fail!" in caplog.text
    server_id_var.reset(token)


# ---------------------------------------------------------------------------
# _proxy_list_prompts_to_gateway tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_proxy_list_prompts_forwards_meta(monkeypatch):
    """_proxy_list_prompts_to_gateway passes _meta via PaginatedRequestParams."""
    from mcpgateway.transports.streamablehttp_transport import _proxy_list_prompts_to_gateway
    from contextlib import asynccontextmanager
    import mcp.types as types

    mock_prompt = types.Prompt(name="p1", description="desc", arguments=[])
    mock_result = MagicMock()
    mock_result.prompts = [mock_prompt]

    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock()
    mock_session.list_prompts = AsyncMock(return_value=mock_result)

    mock_gateway = MagicMock()
    mock_gateway.id = "gw-1"
    mock_gateway.url = "http://upstream"
    mock_gateway.passthrough_headers = []

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", lambda g: {})
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings", MagicMock(mcpgateway_direct_proxy_timeout=30))

    class FakeSession:
        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, *a):
            pass

    @asynccontextmanager
    async def fake_client(url, headers, timeout):
        yield (MagicMock(), MagicMock(), MagicMock())

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", fake_client)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.ClientSession", lambda r, w: FakeSession())

    from mcp.types import RequestParams

    meta = RequestParams.Meta(progressToken="tok-1")
    result = await _proxy_list_prompts_to_gateway(mock_gateway, {}, {}, meta=meta)

    assert len(result) == 1
    assert result[0].name == "p1"
    call_kwargs = mock_session.list_prompts.call_args[1]
    assert call_kwargs["params"] is not None


@pytest.mark.asyncio
async def test_proxy_list_prompts_no_meta(monkeypatch):
    """_proxy_list_prompts_to_gateway passes params=None when no meta."""
    from mcpgateway.transports.streamablehttp_transport import _proxy_list_prompts_to_gateway
    from contextlib import asynccontextmanager

    mock_result = MagicMock()
    mock_result.prompts = []
    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock()
    mock_session.list_prompts = AsyncMock(return_value=mock_result)

    mock_gateway = MagicMock()
    mock_gateway.id = "gw-2"
    mock_gateway.url = "http://upstream"
    mock_gateway.passthrough_headers = []

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", lambda g: {})
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings", MagicMock(mcpgateway_direct_proxy_timeout=30))

    class FakeSession:
        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, *a):
            pass

    @asynccontextmanager
    async def fake_client(url, headers, timeout):
        yield (MagicMock(), MagicMock(), MagicMock())

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", fake_client)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.ClientSession", lambda r, w: FakeSession())

    result = await _proxy_list_prompts_to_gateway(mock_gateway, {}, {}, meta=None)
    assert result == []
    mock_session.list_prompts.assert_called_once_with(params=None)


@pytest.mark.asyncio
async def test_proxy_list_prompts_exception_returns_empty(monkeypatch):
    """_proxy_list_prompts_to_gateway returns [] on exception."""
    from mcpgateway.transports.streamablehttp_transport import _proxy_list_prompts_to_gateway
    from contextlib import asynccontextmanager

    mock_gateway = MagicMock()
    mock_gateway.id = "gw-err"
    mock_gateway.url = "http://upstream"
    mock_gateway.passthrough_headers = []

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", lambda g: {})
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings", MagicMock(mcpgateway_direct_proxy_timeout=30))

    @asynccontextmanager
    async def fake_client(url, headers, timeout):
        raise RuntimeError("upstream down")
        yield

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", fake_client)

    result = await _proxy_list_prompts_to_gateway(mock_gateway, {}, {})
    assert result == []


# ---------------------------------------------------------------------------
# list_prompts tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_prompts_with_server_id(monkeypatch):
    """Test list_prompts returns prompts for a server_id."""
    # Third-Party
    from mcp.types import PromptArgument

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_prompts, prompt_service, server_id_var

    mock_db = MagicMock()
    mock_prompt = MagicMock()
    mock_prompt.name = "prompt1"
    mock_prompt.description = "test prompt"
    mock_prompt.arguments = [PromptArgument(name="arg1", description="desc1", required=None)]

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(prompt_service, "list_server_prompts", AsyncMock(return_value=[mock_prompt]))

    token = server_id_var.set("test-server")
    result = await list_prompts()
    server_id_var.reset(token)

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].name == "prompt1"
    assert result[0].description == "test prompt"
    assert len(result[0].arguments) == 1
    assert result[0].arguments[0].name == "arg1"


@pytest.mark.asyncio
async def test_list_prompts_no_server_id(monkeypatch):
    """Test list_prompts returns prompts when no server_id is set."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_prompts, prompt_service, server_id_var

    mock_db = MagicMock()
    mock_prompt = MagicMock()
    mock_prompt.name = "global_prompt"
    mock_prompt.description = "global test prompt"
    mock_prompt.arguments = []

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
    assert result[0].description == "global test prompt"


@pytest.mark.asyncio
async def test_list_prompts_exception_with_server_id(monkeypatch, caplog):
    """Test list_prompts returns [] and logs exception when server_id is set."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_prompts, prompt_service, server_id_var

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(prompt_service, "list_server_prompts", AsyncMock(side_effect=Exception("server prompt fail!")))

    token = server_id_var.set("test-server")
    with caplog.at_level("ERROR"):
        result = await list_prompts()
        assert result == []
        assert "Error listing Prompts:server prompt fail!" in caplog.text
    server_id_var.reset(token)


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
# list_prompts direct_proxy tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_prompts_direct_proxy_delegates_to_helper(monkeypatch):
    """list_prompts calls _proxy_list_prompts_to_gateway in direct_proxy mode."""
    from mcpgateway.transports.streamablehttp_transport import list_prompts, mcp_app
    from contextlib import asynccontextmanager
    import mcp.types as types

    mock_gateway = MagicMock()
    mock_gateway.id = "gw-dp"
    mock_gateway.gateway_mode = "direct_proxy"

    mock_meta = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.meta = mock_meta

    mock_prompt = types.Prompt(name="upstream-p", description="d", arguments=[])
    proxy_mock = AsyncMock(return_value=[mock_prompt])
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._proxy_list_prompts_to_gateway", proxy_mock)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.check_gateway_access", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings", MagicMock(mcpgateway_direct_proxy_enabled=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda h: "gw-dp")
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default", AsyncMock(return_value=("srv-1", {}, {"email": "u@x.com", "teams": ["t1"], "is_admin": False}))
    )
    type(mcp_app).request_context = property(lambda self: mock_ctx)

    mock_db_result = MagicMock()
    mock_db_result.scalar_one_or_none.return_value = mock_gateway
    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=mock_db_result)

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    result = await list_prompts()
    assert len(result) == 1
    assert result[0].name == "upstream-p"
    proxy_mock.assert_called_once()


@pytest.mark.asyncio
async def test_list_prompts_direct_proxy_access_denied(monkeypatch):
    """list_prompts returns [] when direct_proxy RBAC check fails."""
    from mcpgateway.transports.streamablehttp_transport import list_prompts
    from contextlib import asynccontextmanager

    mock_gateway = MagicMock()
    mock_gateway.id = "gw-deny"
    mock_gateway.gateway_mode = "direct_proxy"

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.check_gateway_access", AsyncMock(return_value=False))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings", MagicMock(mcpgateway_direct_proxy_enabled=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda h: "gw-deny")
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._get_request_context_or_default", AsyncMock(return_value=("srv-1", {}, {"email": "u@x.com", "teams": [], "is_admin": False})))

    mock_db_result = MagicMock()
    mock_db_result.scalar_one_or_none.return_value = mock_gateway
    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=mock_db_result)

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    result = await list_prompts()
    assert result == []


# ---------------------------------------------------------------------------
# _proxy_get_prompt_to_gateway tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_proxy_get_prompt_returns_result(monkeypatch):
    """_proxy_get_prompt_to_gateway fetches prompt from upstream."""
    from mcpgateway.transports.streamablehttp_transport import _proxy_get_prompt_to_gateway
    from contextlib import asynccontextmanager
    import mcp.types as types

    mock_message = types.PromptMessage(role="user", content=types.TextContent(type="text", text="Hello"))
    mock_result = types.GetPromptResult(description="A prompt", messages=[mock_message])

    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock()
    mock_session.get_prompt = AsyncMock(return_value=mock_result)

    mock_gateway = MagicMock()
    mock_gateway.id = "gw-gp"
    mock_gateway.url = "http://upstream"
    mock_gateway.passthrough_headers = []

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", lambda g: {})
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings", MagicMock(mcpgateway_direct_proxy_timeout=30))

    class FakeSession:
        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, *a):
            pass

    @asynccontextmanager
    async def fake_client(url, headers, timeout):
        yield (MagicMock(), MagicMock(), MagicMock())

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", fake_client)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.ClientSession", lambda r, w: FakeSession())

    result = await _proxy_get_prompt_to_gateway(mock_gateway, {}, "my-prompt", {"lang": "en"}, None)

    assert result is not None
    assert result.description == "A prompt"
    mock_session.get_prompt.assert_called_once_with("my-prompt", arguments={"lang": "en"})


@pytest.mark.asyncio
async def test_proxy_get_prompt_forwards_meta_via_send_request(monkeypatch):
    """_proxy_get_prompt_to_gateway uses send_request when _meta is present."""
    from mcpgateway.transports.streamablehttp_transport import _proxy_get_prompt_to_gateway
    from contextlib import asynccontextmanager
    import mcp.types as types

    mock_message = types.PromptMessage(role="user", content=types.TextContent(type="text", text="Hi"))
    mock_result = types.GetPromptResult(description="d", messages=[mock_message])

    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock()
    mock_session.get_prompt = AsyncMock()
    mock_session.send_request = AsyncMock(return_value=mock_result)

    mock_gateway = MagicMock()
    mock_gateway.id = "gw-gp-meta"
    mock_gateway.url = "http://upstream"
    mock_gateway.passthrough_headers = []

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", lambda g: {})
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings", MagicMock(mcpgateway_direct_proxy_timeout=30))

    class FakeSession:
        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, *a):
            pass

    @asynccontextmanager
    async def fake_client(url, headers, timeout):
        yield (MagicMock(), MagicMock(), MagicMock())

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", fake_client)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.ClientSession", lambda r, w: FakeSession())

    meta = {"progressToken": "tok-42"}
    result = await _proxy_get_prompt_to_gateway(mock_gateway, {}, "meta-prompt", None, meta)

    assert result is not None
    mock_session.send_request.assert_called_once()
    mock_session.get_prompt.assert_not_called()


@pytest.mark.asyncio
async def test_proxy_get_prompt_exception_returns_none(monkeypatch):
    """_proxy_get_prompt_to_gateway returns None on exception."""
    from mcpgateway.transports.streamablehttp_transport import _proxy_get_prompt_to_gateway
    from contextlib import asynccontextmanager

    mock_gateway = MagicMock()
    mock_gateway.id = "gw-err"
    mock_gateway.url = "http://upstream"
    mock_gateway.passthrough_headers = []

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", lambda g: {})
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings", MagicMock(mcpgateway_direct_proxy_timeout=30))

    @asynccontextmanager
    async def fake_client(url, headers, timeout):
        raise RuntimeError("upstream down")
        yield

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", fake_client)

    result = await _proxy_get_prompt_to_gateway(mock_gateway, {}, "p", None, None)
    assert result is None


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

    with caplog.at_level("WARNING"):
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

    with caplog.at_level("WARNING"):
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
# get_prompt direct_proxy tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_prompt_direct_proxy_delegates_to_helper(monkeypatch):
    """get_prompt calls _proxy_get_prompt_to_gateway in direct_proxy mode."""
    from mcpgateway.transports.streamablehttp_transport import get_prompt, mcp_app
    from contextlib import asynccontextmanager
    import mcp.types as types

    mock_gateway = MagicMock()
    mock_gateway.id = "gw-dp"
    mock_gateway.gateway_mode = "direct_proxy"

    mock_message = types.PromptMessage(role="user", content=types.TextContent(type="text", text="hi"))
    mock_proxy_result = types.GetPromptResult(description="d", messages=[mock_message])

    proxy_mock = AsyncMock(return_value=mock_proxy_result)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._proxy_get_prompt_to_gateway", proxy_mock)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.check_gateway_access", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings", MagicMock(mcpgateway_direct_proxy_enabled=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda h: "gw-dp")
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default", AsyncMock(return_value=("srv-1", {}, {"email": "u@x.com", "teams": ["t1"], "is_admin": False}))
    )
    type(mcp_app).request_context = property(lambda self: (_ for _ in ()).throw(LookupError))

    mock_db_result = MagicMock()
    mock_db_result.scalar_one_or_none.return_value = mock_gateway
    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=mock_db_result)

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    result = await get_prompt("my-prompt", {"lang": "en"})

    assert result is not None
    assert len(result.messages) == 1
    proxy_mock.assert_called_once()
    call_kwargs = proxy_mock.call_args[1]
    assert call_kwargs["name"] == "my-prompt"
    assert call_kwargs["arguments"] == {"lang": "en"}


@pytest.mark.asyncio
async def test_list_prompts_gateway_not_direct_proxy_mode(monkeypatch):
    """list_prompts falls through to cache mode when gateway exists but not in direct_proxy mode."""
    from mcpgateway.transports.streamablehttp_transport import list_prompts
    from contextlib import asynccontextmanager
    from mcpgateway.transports.streamablehttp_transport import prompt_service

    mock_gateway = MagicMock()
    mock_gateway.id = "gw-cache"
    mock_gateway.gateway_mode = "cache"

    mock_prompt = MagicMock()
    mock_prompt.name = "cached-prompt"
    mock_prompt.description = "desc"
    mock_prompt.arguments = []

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.check_gateway_access", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings", MagicMock(mcpgateway_direct_proxy_enabled=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda h: "gw-cache")
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default", AsyncMock(return_value=("srv-1", {}, {"email": "u@x.com", "teams": ["t1"], "is_admin": False}))
    )
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.prompt_service.list_server_prompts", AsyncMock(return_value=[mock_prompt]))

    mock_db_result = MagicMock()
    mock_db_result.scalar_one_or_none.return_value = mock_gateway
    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=mock_db_result)

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    result = await list_prompts()
    assert len(result) == 1
    assert result[0].name == "cached-prompt"


@pytest.mark.asyncio
async def test_get_prompt_gateway_not_direct_proxy_mode(monkeypatch):
    """get_prompt falls through to cache mode when gateway exists but not in direct_proxy mode."""
    from mcpgateway.transports.streamablehttp_transport import get_prompt
    from contextlib import asynccontextmanager
    import mcp.types as types

    mock_gateway = MagicMock()
    mock_gateway.id = "gw-cache"
    mock_gateway.gateway_mode = "cache"

    mock_message = types.PromptMessage(role="user", content=types.TextContent(type="text", text="Hello"))
    mock_result = types.GetPromptResult(description="A prompt", messages=[mock_message])

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.check_gateway_access", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings", MagicMock(mcpgateway_direct_proxy_enabled=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda h: "gw-cache")
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default", AsyncMock(return_value=("srv-1", {}, {"email": "u@x.com", "teams": ["t1"], "is_admin": False}))
    )
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.prompt_service.get_prompt", AsyncMock(return_value=mock_result))

    mock_db_result = MagicMock()
    mock_db_result.scalar_one_or_none.return_value = mock_gateway
    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=mock_db_result)

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    result = await get_prompt("test-prompt", None)
    assert result is not None
    assert result.description == "A prompt"


# ---------------------------------------------------------------------------
# Gateway not found tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_prompts_gateway_not_found(monkeypatch, caplog):
    """list_prompts logs warning when gateway is not found."""
    from mcpgateway.transports.streamablehttp_transport import list_prompts
    from contextlib import asynccontextmanager

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.check_gateway_access", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings", MagicMock(mcpgateway_direct_proxy_enabled=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda h: "nonexistent-gw")
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default", AsyncMock(return_value=("srv-1", {}, {"email": "u@x.com", "teams": ["t1"], "is_admin": False}))
    )

    mock_db_result = MagicMock()
    mock_db_result.scalar_one_or_none.return_value = None
    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=mock_db_result)

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    with caplog.at_level("WARNING"):
        result = await list_prompts()
        assert "not found" in caplog.text


@pytest.mark.asyncio
async def test_get_prompt_gateway_not_found(monkeypatch, caplog):
    """get_prompt logs warning when gateway is not found."""
    from mcpgateway.transports.streamablehttp_transport import get_prompt
    from contextlib import asynccontextmanager

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.check_gateway_access", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings", MagicMock(mcpgateway_direct_proxy_enabled=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda h: "nonexistent-gw")
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default", AsyncMock(return_value=("srv-1", {}, {"email": "u@x.com", "teams": ["t1"], "is_admin": False}))
    )

    mock_db_result = MagicMock()
    mock_db_result.scalar_one_or_none.return_value = None
    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=mock_db_result)

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    with caplog.at_level("WARNING"):
        result = await get_prompt("test-prompt", None)
        assert "not found" in caplog.text


# ---------------------------------------------------------------------------
# Request context lookup error tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_prompts_no_request_context_for_meta(monkeypatch, caplog):
    """list_prompts handles LookupError when extracting _meta from request context."""
    from mcpgateway.transports.streamablehttp_transport import list_prompts, mcp_app
    from contextlib import asynccontextmanager
    import mcp.types as types

    mock_gateway = MagicMock()
    mock_gateway.id = "gw-dp"
    mock_gateway.gateway_mode = "direct_proxy"

    mock_prompt = types.Prompt(name="upstream-p", description="d", arguments=[])
    proxy_mock = AsyncMock(return_value=[mock_prompt])
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._proxy_list_prompts_to_gateway", proxy_mock)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.check_gateway_access", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings", MagicMock(mcpgateway_direct_proxy_enabled=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda h: "gw-dp")
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default", AsyncMock(return_value=("srv-1", {}, {"email": "u@x.com", "teams": ["t1"], "is_admin": False}))
    )
    type(mcp_app).request_context = property(lambda self: (_ for _ in ()).throw(LookupError("no context")))

    mock_db_result = MagicMock()
    mock_db_result.scalar_one_or_none.return_value = mock_gateway
    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=mock_db_result)

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    with caplog.at_level("DEBUG"):
        result = await list_prompts()
        assert len(result) == 1
        assert result[0].name == "upstream-p"
        proxy_mock.assert_called_once()
        call_kwargs = proxy_mock.call_args[1]
        assert call_kwargs.get("meta") is None


# ---------------------------------------------------------------------------
# Upstream prompt empty result tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_prompt_direct_proxy_empty_result(monkeypatch, caplog):
    """get_prompt returns [] when proxy returns empty result."""
    from mcpgateway.transports.streamablehttp_transport import get_prompt, mcp_app
    from contextlib import asynccontextmanager

    mock_gateway = MagicMock()
    mock_gateway.id = "gw-dp"
    mock_gateway.gateway_mode = "direct_proxy"

    proxy_mock = AsyncMock(return_value=None)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._proxy_get_prompt_to_gateway", proxy_mock)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.check_gateway_access", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings", MagicMock(mcpgateway_direct_proxy_enabled=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda h: "gw-dp")
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default", AsyncMock(return_value=("srv-1", {}, {"email": "u@x.com", "teams": ["t1"], "is_admin": False}))
    )
    type(mcp_app).request_context = property(lambda self: (_ for _ in ()).throw(LookupError))

    mock_db_result = MagicMock()
    mock_db_result.scalar_one_or_none.return_value = mock_gateway
    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=mock_db_result)

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    with caplog.at_level("WARNING"):
        result = await get_prompt("empty-prompt", None)
        assert result == []
        assert "No content returned by upstream prompt" in caplog.text


# ---------------------------------------------------------------------------
# Completion passthrough headers test
# ---------------------------------------------------------------------------
# Completion passthrough headers test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_proxy_complete_passthrough_headers(monkeypatch):
    """_proxy_complete_to_gateway passes through headers from request_headers."""
    from mcpgateway.transports.streamablehttp_transport import _proxy_complete_to_gateway
    from contextlib import asynccontextmanager
    import mcp.types as types

    mock_result = types.Completion(values=["opt1", "opt2"], total=2, hasMore=False)

    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock()
    mock_session.complete = AsyncMock(return_value=mock_result)

    mock_gateway = MagicMock()
    mock_gateway.id = "gw-comp"
    mock_gateway.url = "http://upstream"
    mock_gateway.passthrough_headers = ["x-forwarded-for", "x-request-id"]

    captured_headers = {}

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", lambda g: {})
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings", MagicMock(mcpgateway_direct_proxy_timeout=30))

    class FakeSession:
        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, *a):
            pass

    @asynccontextmanager
    async def fake_client(url, headers, timeout):
        captured_headers.update(headers)
        yield (MagicMock(), MagicMock(), MagicMock())

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", fake_client)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.ClientSession", lambda r, w: FakeSession())

    request_headers = {"x-forwarded-for": "192.168.1.1", "x-request-id": "req-123"}
    mock_ref = MagicMock()
    mock_arg = MagicMock()

    result = await _proxy_complete_to_gateway(mock_gateway, request_headers, {}, ref=mock_ref, argument=mock_arg, context=None, meta=None)

    assert result is not None
    assert captured_headers.get("x-forwarded-for") == "192.168.1.1"
    assert captured_headers.get("x-request-id") == "req-123"


# ---------------------------------------------------------------------------
# Completion result type handling tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_direct_proxy_result_is_dict(monkeypatch):
    """complete returns normalized result when proxy returns a dict."""
    from mcpgateway.transports.streamablehttp_transport import complete
    from contextlib import asynccontextmanager
    import mcp.types as types

    mock_gateway = MagicMock()
    mock_gateway.id = "gw-dp"
    mock_gateway.gateway_mode = "direct_proxy"

    mock_result = {"values": ["a", "b"], "total": 2, "hasMore": False}
    proxy_mock = AsyncMock(return_value=mock_result)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._proxy_complete_to_gateway", proxy_mock)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.check_gateway_access", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings", MagicMock(mcpgateway_direct_proxy_enabled=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda h: "gw-dp")
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default", AsyncMock(return_value=("srv-1", {}, {"email": "u@x.com", "teams": ["t1"], "is_admin": False}))
    )

    mock_db_result = MagicMock()
    mock_db_result.scalar_one_or_none.return_value = mock_gateway
    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=mock_db_result)

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    mock_ref = MagicMock()
    mock_arg = MagicMock()

    result = await complete(mock_ref, mock_arg, None)

    assert isinstance(result, types.Completion)
    assert result.values == ["a", "b"]


@pytest.mark.asyncio
async def test_complete_direct_proxy_result_has_completion_attr(monkeypatch):
    """complete returns normalized result when proxy returns object with completion attr."""
    from mcpgateway.transports.streamablehttp_transport import complete
    from contextlib import asynccontextmanager
    import mcp.types as types

    mock_gateway = MagicMock()
    mock_gateway.id = "gw-dp"
    mock_gateway.gateway_mode = "direct_proxy"

    inner_completion = types.Completion(values=["x", "y"], total=2, hasMore=False)
    mock_result = MagicMock()
    mock_result.completion = inner_completion
    proxy_mock = AsyncMock(return_value=mock_result)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._proxy_complete_to_gateway", proxy_mock)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.check_gateway_access", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings", MagicMock(mcpgateway_direct_proxy_enabled=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda h: "gw-dp")
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default", AsyncMock(return_value=("srv-1", {}, {"email": "u@x.com", "teams": ["t1"], "is_admin": False}))
    )

    mock_db_result = MagicMock()
    mock_db_result.scalar_one_or_none.return_value = mock_gateway
    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=mock_db_result)

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    mock_ref = MagicMock()
    mock_arg = MagicMock()

    result = await complete(mock_ref, mock_arg, None)

    assert isinstance(result, types.Completion)
    assert result.values == ["x", "y"]


@pytest.mark.asyncio
async def test_complete_direct_proxy_result_is_completion_type(monkeypatch):
    """complete returns result directly when proxy returns types.Completion."""
    from mcpgateway.transports.streamablehttp_transport import complete
    from contextlib import asynccontextmanager
    import mcp.types as types

    mock_gateway = MagicMock()
    mock_gateway.id = "gw-dp"
    mock_gateway.gateway_mode = "direct_proxy"

    mock_result = types.Completion(values=["m", "n"], total=2, hasMore=True)
    proxy_mock = AsyncMock(return_value=mock_result)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._proxy_complete_to_gateway", proxy_mock)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.check_gateway_access", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings", MagicMock(mcpgateway_direct_proxy_enabled=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda h: "gw-dp")
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default", AsyncMock(return_value=("srv-1", {}, {"email": "u@x.com", "teams": ["t1"], "is_admin": False}))
    )

    mock_db_result = MagicMock()
    mock_db_result.scalar_one_or_none.return_value = mock_gateway
    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=mock_db_result)

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    mock_ref = MagicMock()
    mock_arg = MagicMock()

    result = await complete(mock_ref, mock_arg, None)

    assert isinstance(result, types.Completion)
    assert result.values == ["m", "n"]
    assert result.hasMore is True


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
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.proxy_user_header", "x-forwarded-user")
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", False)

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
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, types

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
    from mcpgateway.transports.streamablehttp_transport import (
        call_tool,
        request_headers_var,
        types,
        user_context_var,
    )

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
    from mcpgateway.transports.streamablehttp_transport import (
        call_tool,
        request_headers_var,
        user_context_var,
    )

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
    from mcpgateway.transports.streamablehttp_transport import (
        call_tool,
        request_headers_var,
        user_context_var,
    )

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
    from mcpgateway.transports.streamablehttp_transport import (
        call_tool,
        request_headers_var,
        tool_service,
        types,
        user_context_var,
    )

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
    from mcpgateway.transports.streamablehttp_transport import (
        call_tool,
        request_headers_var,
        tool_service,
        types,
        user_context_var,
    )

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

    wrapper = SessionManagerWrapper()

    assert captured_config["stateless"] is False
    assert captured_config["event_store"] is not None
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
    import httpx

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
        caplog.at_level("WARNING"),
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

    mock_resolve = MagicMock(return_value=["team-a", "team-b"])

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer session-tok")])
    sent = []

    async def send(msg):
        sent.append(msg)

    with (
        patch("mcpgateway.auth._resolve_teams_from_db_sync", mock_resolve),
        patch("mcpgateway.cache.auth_cache.get_auth_cache") as mock_get_cache,
    ):
        mock_auth_cache = MagicMock()
        mock_auth_cache.get_team_membership_valid_sync.return_value = True
        mock_get_cache.return_value = mock_auth_cache
        result = await streamable_http_auth(scope, None, send)

    assert result is True
    user_ctx = tr.user_context_var.get()
    assert user_ctx["teams"] == ["team-a", "team-b"]
    mock_resolve.assert_called_once_with("user@example.com", is_admin=False)


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
        """Test proxy list_tools forwards passthrough headers."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-123"
        mock_gateway.url = "http://remote-gateway.example.com/mcp"
        mock_gateway.passthrough_headers = ["X-Custom-Header", "X-Request-ID"]

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

        @asynccontextmanager
        async def mock_client(*args, **kwargs):
            headers = kwargs.get("headers", {})
            # Verify passthrough headers are included
            assert "X-Custom-Header" in headers
            assert headers["X-Custom-Header"] == "custom-value"
            assert "X-Request-ID" in headers
            assert headers["X-Request-ID"] == "req-456"
            yield (None, None, lambda: "session-id")

        with patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", mock_client):
            with patch("mcpgateway.transports.streamablehttp_transport.ClientSession", return_value=mock_session):
                with patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}):
                    await tr._proxy_list_tools_to_gateway(mock_gateway, request_headers, {}, None)

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
        """Test proxy list_resources forwards passthrough headers."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-456"
        mock_gateway.url = "http://remote-gateway.example.com/mcp"
        mock_gateway.passthrough_headers = ["X-Tenant-ID", "X-Request-ID"]

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

        @asynccontextmanager
        async def mock_client(*args, **kwargs):
            headers = kwargs.get("headers", {})
            # Verify passthrough headers are included
            assert "X-Tenant-ID" in headers
            assert headers["X-Tenant-ID"] == "tenant-abc"
            assert "X-Request-ID" in headers
            assert headers["X-Request-ID"] == "req-789"
            yield (None, None, lambda: "session-id")

        with patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", mock_client):
            with patch("mcpgateway.transports.streamablehttp_transport.ClientSession", return_value=mock_session):
                with patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}):
                    await tr._proxy_list_resources_to_gateway(mock_gateway, request_headers, {}, None)

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
        """Test proxy read_resource forwards passthrough headers."""
        mock_gateway = MagicMock()
        mock_gateway.id = "gw-789"
        mock_gateway.url = "http://remote-gateway.example.com/mcp"
        mock_gateway.passthrough_headers = ["X-Tenant-ID"]

        mock_result = MagicMock()
        mock_result.contents = []

        mock_session = AsyncMock()
        mock_session.read_resource = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        @asynccontextmanager
        async def mock_client(*args, **kwargs):
            headers = kwargs.get("headers", {})
            assert "X-Tenant-ID" in headers
            assert headers["X-Tenant-ID"] == "tenant-123"
            yield (None, None, lambda: "session-id")

        tr.request_headers_var.set({"x-tenant-id": "tenant-123"})

        with patch("mcpgateway.transports.streamablehttp_transport.streamablehttp_client", mock_client):
            with patch("mcpgateway.transports.streamablehttp_transport.ClientSession", return_value=mock_session):
                with patch("mcpgateway.transports.streamablehttp_transport.build_gateway_auth_headers", return_value={}):
                    await tr._proxy_read_resource_to_gateway(mock_gateway, "file:///test.txt", {}, None)

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
        tr.user_context_var.set({"email": "user@example.com", "teams": ["team1"]})

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
        tr.user_context_var.set({"email": "user@example.com", "teams": ["team1"]})

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
        tr.user_context_var.set({"email": "user@example.com", "teams": []})

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
        tr.user_context_var.set({"email": "user@example.com", "teams": []})

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
        tr.user_context_var.set({"email": "user@example.com", "teams": ["team1"]})

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
        tr.user_context_var.set({"email": "user@example.com", "teams": ["team1"]})

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
        tr.user_context_var.set({"email": "user@example.com", "teams": ["team1"]})

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
        tr.user_context_var.set({"email": "user@example.com", "teams": ["team1"]})

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
        tr.user_context_var.set({"email": "user@example.com", "teams": ["team1"]})

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
        tr.user_context_var.set({"email": "user@example.com", "teams": ["team1"]})

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
        tr.user_context_var.set({"email": "user@example.com", "teams": ["team1"]})

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
        tr.user_context_var.set({"email": "user@example.com", "teams": ["team1"]})

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
        tr.user_context_var.set({"email": "user@example.com", "teams": []})

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
        tr.user_context_var.set({"email": "user@example.com", "teams": []})

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
        mock_request_ctx = MagicMock()
        mock_request_ctx.meta = mock_meta

        mock_content = MagicMock()
        mock_content.text = "Proxied content with meta"

        tr.server_id_var.set("server-123")
        tr.request_headers_var.set({"x-context-forge-gateway-id": "gw-direct"})
        tr.user_context_var.set({"email": "user@example.com", "teams": ["team1"]})

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
        tr.user_context_var.set({"email": "user@example.com", "teams": []})

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
        tr.user_context_var.set({"email": "user@example.com", "teams": []})

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
        tr.user_context_var.set({"email": "user@test.com", "teams": ["team1"], "is_admin": False})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            with patch("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", return_value="gw-direct"):
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
        tr.user_context_var.set({"email": "user@test.com", "teams": ["team1"], "is_admin": False})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            with patch("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", return_value="gw-direct"):
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
        tr.user_context_var.set({"email": "user@test.com", "teams": ["team1"], "is_admin": False})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            with patch("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", return_value="gw-direct"):
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
        tr.user_context_var.set({"email": "user@test.com", "teams": ["team1"], "is_admin": False})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            with patch("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", return_value="gw-cache"):
                with patch.object(tr.tool_service, "invoke_tool", mock_invoke_normal):
                    with patch("mcpgateway.transports.streamablehttp_transport.settings") as mock_settings:
                        mock_settings.mcpgateway_session_affinity_enabled = False
                        result = await tr.call_tool("my_tool", {"arg": "value"})

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
        tr.user_context_var.set({"email": "user@test.com", "teams": ["team1"], "is_admin": False})

        with patch("mcpgateway.transports.streamablehttp_transport.get_db", mock_get_db):
            with patch("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", return_value="gw-direct"):
                with patch.object(tr.tool_service, "invoke_tool_direct", mock_invoke_direct):
                    with patch.object(tr.tool_service, "invoke_tool", mock_invoke_normal):
                        with patch("mcpgateway.transports.streamablehttp_transport.settings") as mock_settings:
                            mock_settings.mcpgateway_direct_proxy_enabled = False
                            mock_settings.mcpgateway_session_affinity_enabled = False
                            result = await tr.call_tool("my_tool", {"arg": "value"})

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
    from mcpgateway.transports.streamablehttp_transport import list_resources, request_headers_var, resource_service, server_id_var

    mock_gateway = MagicMock()
    mock_gateway.id = "gw-cache"
    mock_gateway.gateway_mode = "cache"

    mock_resource = MagicMock()
    mock_resource.name = "r"
    mock_resource.description = "desc"
    mock_resource.mime_type = "text/plain"
    mock_resource.uri = "file:///r.txt"

    mock_db_result = MagicMock()
    mock_db_result.scalar_one_or_none.return_value = mock_gateway
    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=mock_db_result)

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.check_gateway_access", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings", MagicMock(mcpgateway_direct_proxy_enabled=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda h: "gw-cache")
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default",
        AsyncMock(return_value=("srv-1", {}, {"email": "u@x.com", "teams": ["t1"], "is_admin": False})),
    )
    monkeypatch.setattr(resource_service, "list_server_resources", AsyncMock(return_value=[mock_resource]))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    header_token = request_headers_var.set({"x-context-forge-gateway-id": "gw-cache"})
    token = server_id_var.set("srv-1")
    result = await list_resources()
    server_id_var.reset(token)
    request_headers_var.reset(header_token)

    assert len(result) == 1
    assert result[0].name == "r"


@pytest.mark.asyncio
async def test_complete_gateway_not_direct_proxy_mode(monkeypatch):
    """complete falls through to cache mode when gateway not in direct_proxy mode."""
    from mcpgateway.transports.streamablehttp_transport import complete
    from contextlib import asynccontextmanager
    import mcp.types as types
    from mcpgateway.transports.streamablehttp_transport import completion_service

    mock_gateway = MagicMock()
    mock_gateway.id = "gw-cache"
    mock_gateway.gateway_mode = "cache"

    mock_result = types.Completion(values=["opt"], total=1, hasMore=False)

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.check_gateway_access", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings", MagicMock(mcpgateway_direct_proxy_enabled=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda h: "gw-cache")
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default", AsyncMock(return_value=("srv-1", {}, {"email": "u@x.com", "teams": ["t1"], "is_admin": False}))
    )
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.completion_service.handle_completion", AsyncMock(return_value=mock_result))

    mock_db_result = MagicMock()
    mock_db_result.scalar_one_or_none.return_value = mock_gateway
    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=mock_db_result)

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    mock_ref = MagicMock()
    mock_arg = MagicMock()

    result = await complete(mock_ref, mock_arg, None)

    assert isinstance(result, types.Completion)
    assert result.values == ["opt"]


@pytest.mark.asyncio
async def test_complete_gateway_not_found(monkeypatch, caplog):
    """complete logs warning and falls through when gateway not found."""
    from mcpgateway.transports.streamablehttp_transport import complete
    from contextlib import asynccontextmanager
    import mcp.types as types
    from mcpgateway.transports.streamablehttp_transport import completion_service

    mock_result = types.Completion(values=["opt"], total=1, hasMore=False)

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.check_gateway_access", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings", MagicMock(mcpgateway_direct_proxy_enabled=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda h: "nonexistent-gw")
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default", AsyncMock(return_value=("srv-1", {}, {"email": "u@x.com", "teams": ["t1"], "is_admin": False}))
    )
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.completion_service.handle_completion", AsyncMock(return_value=mock_result))

    mock_db_result = MagicMock()
    mock_db_result.scalar_one_or_none.return_value = None
    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=mock_db_result)

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    mock_ref = MagicMock()
    mock_arg = MagicMock()

    with caplog.at_level("WARNING"):
        result = await complete(mock_ref, mock_arg, None)
        assert "not found" in caplog.text

    assert isinstance(result, types.Completion)
    assert result.values == ["a", "b"]


@pytest.mark.asyncio
async def test_complete_direct_proxy_result_has_completion_attr(monkeypatch):
    """complete returns normalized result when proxy returns object with completion attr."""
    from mcpgateway.transports.streamablehttp_transport import complete
    from contextlib import asynccontextmanager
    import mcp.types as types

    mock_gateway = MagicMock()
    mock_gateway.id = "gw-dp"
    mock_gateway.gateway_mode = "direct_proxy"

    inner_completion = types.Completion(values=["x", "y"], total=2, hasMore=False)
    mock_result = MagicMock()
    mock_result.completion = inner_completion
    proxy_mock = AsyncMock(return_value=mock_result)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._proxy_complete_to_gateway", proxy_mock)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.check_gateway_access", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings", MagicMock(mcpgateway_direct_proxy_enabled=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda h: "gw-dp")
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default", AsyncMock(return_value=("srv-1", {}, {"email": "u@x.com", "teams": ["t1"], "is_admin": False}))
    )

    mock_db_result = MagicMock()
    mock_db_result.scalar_one_or_none.return_value = mock_gateway
    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=mock_db_result)

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    mock_ref = MagicMock()
    mock_arg = MagicMock()

    result = await complete(mock_ref, mock_arg, None)

    assert isinstance(result, types.Completion)
    assert result.values == ["x", "y"]


@pytest.mark.asyncio
async def test_complete_direct_proxy_result_is_completion_type(monkeypatch):
    """complete returns result directly when proxy returns types.Completion."""
    from mcpgateway.transports.streamablehttp_transport import complete
    from contextlib import asynccontextmanager
    import mcp.types as types

    mock_gateway = MagicMock()
    mock_gateway.id = "gw-dp"
    mock_gateway.gateway_mode = "direct_proxy"

    mock_result = types.Completion(values=["m", "n"], total=2, hasMore=True)
    proxy_mock = AsyncMock(return_value=mock_result)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport._proxy_complete_to_gateway", proxy_mock)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.check_gateway_access", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings", MagicMock(mcpgateway_direct_proxy_enabled=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda h: "gw-dp")
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default", AsyncMock(return_value=("srv-1", {}, {"email": "u@x.com", "teams": ["t1"], "is_admin": False}))
    )

    mock_db_result = MagicMock()
    mock_db_result.scalar_one_or_none.return_value = mock_gateway
    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=mock_db_result)

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    mock_ref = MagicMock()
    mock_arg = MagicMock()

    result = await complete(mock_ref, mock_arg, None)

    assert isinstance(result, types.Completion)
    assert result.values == ["m", "n"]
    assert result.hasMore is True


@pytest.mark.asyncio
async def test_complete_gateway_not_direct_proxy_mode(monkeypatch):
    """complete falls through to cache mode when gateway not in direct_proxy mode."""
    from mcpgateway.transports.streamablehttp_transport import complete
    from contextlib import asynccontextmanager
    import mcp.types as types
    from mcpgateway.transports.streamablehttp_transport import completion_service

    mock_gateway = MagicMock()
    mock_gateway.id = "gw-cache"
    mock_gateway.gateway_mode = "cache"

    mock_result = types.Completion(values=["opt"], total=1, hasMore=False)

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.check_gateway_access", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings", MagicMock(mcpgateway_direct_proxy_enabled=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda h: "gw-cache")
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default", AsyncMock(return_value=("srv-1", {}, {"email": "u@x.com", "teams": ["t1"], "is_admin": False}))
    )
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.completion_service.handle_completion", AsyncMock(return_value=mock_result))

    mock_db_result = MagicMock()
    mock_db_result.scalar_one_or_none.return_value = mock_gateway
    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=mock_db_result)

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    mock_ref = MagicMock()
    mock_arg = MagicMock()

    result = await complete(mock_ref, mock_arg, None)

    assert isinstance(result, types.Completion)
    assert result.values == ["opt"]


@pytest.mark.asyncio
async def test_complete_gateway_not_found(monkeypatch, caplog):
    """complete logs warning and falls through when gateway not found."""
    from mcpgateway.transports.streamablehttp_transport import complete
    from contextlib import asynccontextmanager
    import mcp.types as types
    from mcpgateway.transports.streamablehttp_transport import completion_service

    mock_result = types.Completion(values=["opt"], total=1, hasMore=False)

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.check_gateway_access", AsyncMock(return_value=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings", MagicMock(mcpgateway_direct_proxy_enabled=True))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.extract_gateway_id_from_headers", lambda h: "nonexistent-gw")
    monkeypatch.setattr(
        "mcpgateway.transports.streamablehttp_transport._get_request_context_or_default", AsyncMock(return_value=("srv-1", {}, {"email": "u@x.com", "teams": ["t1"], "is_admin": False}))
    )
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.completion_service.handle_completion", AsyncMock(return_value=mock_result))

    mock_db_result = MagicMock()
    mock_db_result.scalar_one_or_none.return_value = None
    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=mock_db_result)

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    mock_ref = MagicMock()
    mock_arg = MagicMock()

    with caplog.at_level("WARNING"):
        result = await complete(mock_ref, mock_arg, None)
        assert "not found" in caplog.text

    assert isinstance(result, types.Completion)
