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

import asyncio
import types
import pytest

import mcpgateway.transports.streamablehttp_transport as transport


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
# list_resources tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_resources_with_server_id(monkeypatch):
    """Test list_resources returns resources for a server_id."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_resources, resource_service, server_id_var

    mock_db = MagicMock()
    mock_resource = MagicMock()
    mock_resource.uri = "file:///test.txt"
    mock_resource.name = "test resource"
    mock_resource.description = "test description"
    mock_resource.mime_type = "text/plain"

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(resource_service, "list_server_resources", AsyncMock(return_value=[mock_resource]))

    token = server_id_var.set("test-server")
    result = await list_resources()
    server_id_var.reset(token)

    assert isinstance(result, list)
    assert len(result) == 1
    assert str(result[0].uri) == "file:///test.txt"
    assert result[0].name == "test resource"
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
    assert result[0].name == "global resource"


@pytest.mark.asyncio
async def test_list_resources_exception_with_server_id(monkeypatch, caplog):
    """Test list_resources returns [] and logs exception when server_id is set."""
    # First-Party
    from mcpgateway.transports.streamablehttp_transport import list_resources, resource_service, server_id_var

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)
    monkeypatch.setattr(resource_service, "list_server_resources", AsyncMock(side_effect=Exception("server resource fail!")))

    token = server_id_var.set("test-server")
    with caplog.at_level("ERROR"):
        result = await list_resources()
        assert result == []
        assert "Error listing Resources:server resource fail!" in caplog.text
    server_id_var.reset(token)


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
    from mcpgateway.transports.streamablehttp_transport import list_resource_templates, resource_service, user_context_var

    mock_db = MagicMock()
    mock_template = MagicMock()
    mock_template.model_dump = MagicMock(return_value={"uri_template": "file:///{path}", "name": "Files"})

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    # Track what parameters were passed to the service
    captured_calls = []

    async def mock_list_templates(db, user_email=None, token_teams=None):
        captured_calls.append({"user_email": user_email, "token_teams": token_teams})
        return [mock_template]

    monkeypatch.setattr(resource_service, "list_resource_templates", mock_list_templates)

    # Set public-only user context (no auth, teams=None which becomes [])
    token = user_context_var.set({"email": None, "teams": None, "is_admin": False})
    try:
        result = await list_resource_templates()
    finally:
        user_context_var.reset(token)

    # Verify the service was called with public-only access (empty teams)
    assert len(captured_calls) == 1
    assert captured_calls[0]["user_email"] is None
    assert captured_calls[0]["token_teams"] == []  # Public-only (secure default)

    assert isinstance(result, list)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_list_resource_templates_admin_unrestricted(monkeypatch):
    """Test list_resource_templates passes token_teams=None for admin users without team restrictions."""
    from mcpgateway.transports.streamablehttp_transport import list_resource_templates, resource_service, user_context_var

    mock_db = MagicMock()
    mock_template = MagicMock()
    mock_template.model_dump = MagicMock(return_value={"uri_template": "file:///{path}", "name": "Files"})

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    captured_calls = []

    async def mock_list_templates(db, user_email=None, token_teams=None):
        captured_calls.append({"user_email": user_email, "token_teams": token_teams})
        return [mock_template]

    monkeypatch.setattr(resource_service, "list_resource_templates", mock_list_templates)

    # Set admin user context with no team restrictions
    token = user_context_var.set({"email": "admin@example.com", "teams": None, "is_admin": True})
    try:
        result = await list_resource_templates()
    finally:
        user_context_var.reset(token)

    # Verify the service was called with admin unrestricted access
    assert len(captured_calls) == 1
    assert captured_calls[0]["user_email"] is None  # Admin bypass clears email
    assert captured_calls[0]["token_teams"] is None  # Unrestricted

    assert isinstance(result, list)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_list_resource_templates_team_scoped(monkeypatch):
    """Test list_resource_templates passes token_teams for team-scoped access."""
    from mcpgateway.transports.streamablehttp_transport import list_resource_templates, resource_service, user_context_var

    mock_db = MagicMock()
    mock_template = MagicMock()
    mock_template.model_dump = MagicMock(return_value={"uri_template": "file:///{path}", "name": "Files"})

    @asynccontextmanager
    async def fake_get_db():
        yield mock_db

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)

    captured_calls = []

    async def mock_list_templates(db, user_email=None, token_teams=None):
        captured_calls.append({"user_email": user_email, "token_teams": token_teams})
        return [mock_template]

    monkeypatch.setattr(resource_service, "list_resource_templates", mock_list_templates)

    # Set user context with specific team membership
    token = user_context_var.set({"email": "user@example.com", "teams": ["team-1", "team-2"], "is_admin": False})
    try:
        result = await list_resource_templates()
    finally:
        user_context_var.reset(token)

    # Verify the service was called with team-scoped access
    assert len(captured_calls) == 1
    assert captured_calls[0]["user_email"] == "user@example.com"
    assert captured_calls[0]["token_teams"] == ["team-1", "team-2"]

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
    with caplog.at_level("WARNING"):
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
    with caplog.at_level("WARNING"):
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


def _make_scope(path: str, headers: list[tuple[bytes, bytes]] | None = None, method: str = "POST") -> Scope:
    return {
        "type": "http",
        "method": method,
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


@pytest.mark.asyncio
async def test_streamable_http_auth_wrong_scheme(monkeypatch):
    """Auth returns False and sends 401 if Authorization is not Bearer and mcp_require_auth=True."""

    async def fake_verify(token):
        raise AssertionError("Should not be called")

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)
    # Enable strict auth mode to test 401 behavior
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", True)
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
    """Test handle_streamable_http logs and raises on exception."""
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

    async def send(msg):
        pass

    with pytest.raises(RuntimeError):
        await wrapper.handle_streamable_http(scope, None, send)
    await wrapper.shutdown()
    assert "Error handling streamable HTTP request" in caplog.text


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

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer token")])
    sent = []

    async def send(msg):
        sent.append(msg)

    with (
        patch("mcpgateway.cache.auth_cache.get_auth_cache", return_value=mock_auth_cache),
        patch("mcpgateway.transports.streamablehttp_transport.SessionLocal", return_value=mock_db),
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
    eid2 = await store.store_event("s1", {"id": 2})
    # Manually corrupt the second slot so entry.seq_num != expected seq
    buffer = store.streams["s1"]
    idx = 1 % store.max_events_per_stream
    entry = buffer.entries[idx]
    if entry is not None:
        # Create a new entry with a different seq_num to simulate overwrite
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
    import asyncio

    with patch("mcpgateway.transports.streamablehttp_transport.SessionLocal") as mock_session_local:
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db

        from mcpgateway.transports.streamablehttp_transport import get_db

        with pytest.raises(asyncio.CancelledError):
            async with get_db() as db:
                raise asyncio.CancelledError()

        mock_db.rollback.assert_called_once()
        mock_db.close.assert_called()


@pytest.mark.asyncio
async def test_get_db_cancelled_error_rollback_fails():
    """get_db handles rollback failure during CancelledError."""
    import asyncio

    with patch("mcpgateway.transports.streamablehttp_transport.SessionLocal") as mock_session_local:
        mock_db = MagicMock()
        mock_db.rollback.side_effect = Exception("rollback fail")
        mock_session_local.return_value = mock_db

        from mcpgateway.transports.streamablehttp_transport import get_db

        with pytest.raises(asyncio.CancelledError):
            async with get_db() as db:
                raise asyncio.CancelledError()

        mock_db.close.assert_called()


@pytest.mark.asyncio
async def test_get_db_cancelled_error_close_fails():
    """get_db handles close failure during CancelledError."""
    import asyncio

    with patch("mcpgateway.transports.streamablehttp_transport.SessionLocal") as mock_session_local:
        mock_db = MagicMock()
        # close is called twice: once in the CancelledError handler (line 431), then in finally (line 445).
        # The first call (in the handler) should fail; the second (in finally) should succeed.
        mock_db.close.side_effect = [Exception("close fail"), None]
        mock_session_local.return_value = mock_db

        from mcpgateway.transports.streamablehttp_transport import get_db

        with pytest.raises(asyncio.CancelledError):
            async with get_db() as db:
                raise asyncio.CancelledError()


@pytest.mark.asyncio
async def test_get_db_exception_rollback_fails_then_invalidate():
    """get_db calls invalidate() when rollback fails on exception."""
    with patch("mcpgateway.transports.streamablehttp_transport.SessionLocal") as mock_session_local:
        mock_db = MagicMock()
        mock_db.rollback.side_effect = Exception("rollback fail")
        mock_session_local.return_value = mock_db

        from mcpgateway.transports.streamablehttp_transport import get_db

        with pytest.raises(ValueError, match="test error"):
            async with get_db() as db:
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

        from mcpgateway.transports.streamablehttp_transport import get_db

        with pytest.raises(ValueError, match="test error"):
            async with get_db() as db:
                raise ValueError("test error")

        mock_db.rollback.assert_called_once()
        mock_db.invalidate.assert_called_once()
        mock_db.close.assert_called()


# ---------------------------------------------------------------------------
# get_user_email_from_context edge cases (Line 458)
# ---------------------------------------------------------------------------


def test_get_user_email_from_context_non_dict():
    """get_user_email_from_context returns str(user) for non-dict user context."""
    from mcpgateway.transports.streamablehttp_transport import get_user_email_from_context, user_context_var

    token = user_context_var.set("someuser@test.com")
    try:
        result = get_user_email_from_context()
        assert result == "someuser@test.com"  # Line 458: str(user)
    finally:
        user_context_var.reset(token)


def test_get_user_email_from_context_empty():
    """get_user_email_from_context returns 'unknown' for empty/falsy user context."""
    from mcpgateway.transports.streamablehttp_transport import get_user_email_from_context, user_context_var

    token = user_context_var.set("")
    try:
        result = get_user_email_from_context()
        assert result == "unknown"  # Line 458: not user -> "unknown"
    finally:
        user_context_var.reset(token)


def test_get_user_email_from_context_sub_fallback():
    """get_user_email_from_context uses sub when email is not present."""
    from mcpgateway.transports.streamablehttp_transport import get_user_email_from_context, user_context_var

    token = user_context_var.set({"sub": "sub@test.com"})
    try:
        result = get_user_email_from_context()
        assert result == "sub@test.com"  # Line 457: user.get("sub")
    finally:
        user_context_var.reset(token)


def test_get_user_email_from_context_no_email_no_sub():
    """get_user_email_from_context returns 'unknown' when dict has no email or sub."""
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
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, types, mcp_app

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
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, mcp_app, types

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
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, user_context_var, types

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
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, user_context_var, types

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
    from mcpgateway.transports.streamablehttp_transport import (
        call_tool, tool_service, user_context_var, request_headers_var, types
    )

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
    from mcpgateway.transports.streamablehttp_transport import list_tools, server_id_var, tool_service, user_context_var

    mock_db = MagicMock()
    mock_tool = MagicMock()
    mock_tool.name = "admin_tool"
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
    from mcpgateway.transports.streamablehttp_transport import list_tools, server_id_var, tool_service, user_context_var

    mock_db = MagicMock()
    mock_tool = MagicMock()
    mock_tool.name = "public_tool"
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
    from mcpgateway.transports.streamablehttp_transport import list_prompts, server_id_var, prompt_service, user_context_var

    mock_db = MagicMock()
    mock_prompt = MagicMock()
    mock_prompt.name = "admin_prompt"
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
    from mcp.types import PromptMessage, TextContent
    from mcpgateway.transports.streamablehttp_transport import get_prompt, prompt_service, user_context_var, types

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
    from mcp.types import PromptMessage, TextContent
    from mcpgateway.transports.streamablehttp_transport import get_prompt, prompt_service, user_context_var, types

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
    from mcpgateway.transports.streamablehttp_transport import list_resources, server_id_var, resource_service, user_context_var

    mock_db = MagicMock()
    mock_resource = MagicMock()
    mock_resource.uri = "file:///admin.txt"
    mock_resource.name = "admin resource"
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
    from pydantic import AnyUrl
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
    from pydantic import AnyUrl
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
    from mcpgateway.transports.streamablehttp_transport import set_logging_level
    from mcp import types as mcp_types

    with patch("mcpgateway.transports.streamablehttp_transport.logging_service") as mock_ls:
        mock_ls.set_level = AsyncMock()
        result = await set_logging_level("debug")
        assert isinstance(result, mcp_types.EmptyResult)
        mock_ls.set_level.assert_called_once()


@pytest.mark.asyncio
async def test_set_logging_level_warning():
    """Test set_logging_level with warning level."""
    from mcpgateway.transports.streamablehttp_transport import set_logging_level
    from mcp import types as mcp_types

    with patch("mcpgateway.transports.streamablehttp_transport.logging_service") as mock_ls:
        mock_ls.set_level = AsyncMock()
        result = await set_logging_level("warning")
        assert isinstance(result, mcp_types.EmptyResult)
        mock_ls.set_level.assert_called_once()


@pytest.mark.asyncio
async def test_set_logging_level_error():
    """Test set_logging_level with error level."""
    from mcpgateway.transports.streamablehttp_transport import set_logging_level
    from mcp import types as mcp_types

    with patch("mcpgateway.transports.streamablehttp_transport.logging_service") as mock_ls:
        mock_ls.set_level = AsyncMock()
        result = await set_logging_level("error")
        assert isinstance(result, mcp_types.EmptyResult)


@pytest.mark.asyncio
async def test_set_logging_level_critical():
    """Test set_logging_level with critical level."""
    from mcpgateway.transports.streamablehttp_transport import set_logging_level
    from mcp import types as mcp_types

    with patch("mcpgateway.transports.streamablehttp_transport.logging_service") as mock_ls:
        mock_ls.set_level = AsyncMock()
        result = await set_logging_level("critical")
        assert isinstance(result, mcp_types.EmptyResult)


@pytest.mark.asyncio
async def test_set_logging_level_notice():
    """Test set_logging_level with notice maps to INFO."""
    from mcpgateway.transports.streamablehttp_transport import set_logging_level
    from mcpgateway.common.models import LogLevel
    from mcp import types as mcp_types

    with patch("mcpgateway.transports.streamablehttp_transport.logging_service") as mock_ls:
        mock_ls.set_level = AsyncMock()
        result = await set_logging_level("notice")
        assert isinstance(result, mcp_types.EmptyResult)
        mock_ls.set_level.assert_called_once_with(LogLevel.INFO)


@pytest.mark.asyncio
async def test_set_logging_level_unknown_defaults_to_info():
    """Test set_logging_level with unknown level defaults to INFO."""
    from mcpgateway.transports.streamablehttp_transport import set_logging_level
    from mcpgateway.common.models import LogLevel
    from mcp import types as mcp_types

    with patch("mcpgateway.transports.streamablehttp_transport.logging_service") as mock_ls:
        mock_ls.set_level = AsyncMock()
        result = await set_logging_level("unknown_level")
        assert isinstance(result, mcp_types.EmptyResult)
        mock_ls.set_level.assert_called_once_with(LogLevel.INFO)


@pytest.mark.asyncio
async def test_set_logging_level_exception():
    """Test set_logging_level returns EmptyResult on exception."""
    from mcpgateway.transports.streamablehttp_transport import set_logging_level
    from mcp import types as mcp_types

    with patch("mcpgateway.transports.streamablehttp_transport.logging_service") as mock_ls:
        mock_ls.set_level = AsyncMock(side_effect=Exception("level error"))
        result = await set_logging_level("info")
        assert isinstance(result, mcp_types.EmptyResult)


# ---------------------------------------------------------------------------
# complete function (Lines 1177-1221)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_dict_result(monkeypatch):
    """Test complete returns Completion from dict result (line 1188-1190)."""
    from mcpgateway.transports.streamablehttp_transport import complete
    from mcp import types as mcp_types

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
async def test_complete_nested_completion(monkeypatch):
    """Test complete handles nested completion result (line 1200-1202)."""
    from mcpgateway.transports.streamablehttp_transport import complete
    from mcp import types as mcp_types

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
    from mcpgateway.transports.streamablehttp_transport import complete
    from mcp import types as mcp_types

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
    from mcpgateway.transports.streamablehttp_transport import complete
    from mcp import types as mcp_types

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
    from mcpgateway.transports.streamablehttp_transport import complete
    from mcp import types as mcp_types

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
    from mcpgateway.transports.streamablehttp_transport import complete
    from mcp import types as mcp_types

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
    from mcpgateway.transports.streamablehttp_transport import complete
    from mcp import types as mcp_types

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
    from mcpgateway.transports.streamablehttp_transport import complete
    from mcp import types as mcp_types

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
    from mcpgateway.transports.streamablehttp_transport import complete
    from mcp import types as mcp_types

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
# streamable_http_auth: proxy fallback on JWT failure (Lines 1862-1864, 1875-1883)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streamable_http_auth_proxy_user_fallback_on_jwt_failure(monkeypatch):
    """Test auth falls back to proxy user when JWT verification fails (lines 1875-1883)."""
    async def fake_verify(token):
        raise ValueError("invalid token")

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.trust_proxy_auth", True)
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
    assert result is True  # Proxy fallback succeeded
    assert sent == []  # No 401 sent

    user_ctx = tr.user_context_var.get()
    assert user_ctx["email"] == "proxy_fallback@example.com"
    assert user_ctx["teams"] == []
    assert user_ctx["is_admin"] is False


@pytest.mark.asyncio
async def test_streamable_http_auth_proxy_user_context_on_valid_jwt(monkeypatch):
    """Test auth uses proxy_user for context when user_payload is not a dict (line 1862-1864)."""
    async def fake_verify(token):
        # Return something that is truthy but not a dict
        return "string_payload"

    monkeypatch.setattr(tr, "verify_credentials", fake_verify)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.trust_proxy_auth", True)
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

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer token")])
    sent = []

    async def send(msg):
        sent.append(msg)

    with (
        patch("mcpgateway.cache.auth_cache.get_auth_cache", return_value=mock_auth_cache),
        patch("mcpgateway.transports.streamablehttp_transport.SessionLocal", return_value=mock_db),
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
async def test_streamable_http_auth_rollback_exception_ignored(monkeypatch):
    """Test auth ignores rollback exception in finally block (lines 1850-1851)."""
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

    # Mock DB where rollback raises (line 1850-1851)
    mock_db = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = ["team_a"]
    mock_execute = MagicMock()
    mock_execute.scalars.return_value = mock_scalars
    mock_db.execute.return_value = mock_execute
    mock_db.rollback.side_effect = Exception("rollback error")

    scope = _make_scope("/servers/1/mcp", headers=[(b"authorization", b"Bearer token")])
    sent = []

    async def send(msg):
        sent.append(msg)

    with (
        patch("mcpgateway.cache.auth_cache.get_auth_cache", return_value=mock_auth_cache),
        patch("mcpgateway.transports.streamablehttp_transport.SessionLocal", return_value=mock_db),
    ):
        result = await streamable_http_auth(scope, None, send)

    # Should still succeed despite rollback failure
    assert result is True
    assert sent == []
    mock_db.close.assert_called_once()


# ---------------------------------------------------------------------------
# call_tool: structured content from model_dump fallback (Lines 737-738, 744-745)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_tool_structured_content_getattr_exception(monkeypatch):
    """Test call_tool handles getattr exception for structured_content (lines 737-738)."""
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, types

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
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, types

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
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, types

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
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, types

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
    from pydantic import AnyUrl
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
    from mcp.types import PromptMessage, TextContent
    from mcpgateway.transports.streamablehttp_transport import get_prompt, prompt_service, user_context_var, mcp_app, types

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
    from mcp.types import PromptMessage, TextContent
    from mcpgateway.transports.streamablehttp_transport import get_prompt, prompt_service, user_context_var, mcp_app

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
    from pydantic import AnyUrl
    from mcpgateway.transports.streamablehttp_transport import read_resource, resource_service, user_context_var, mcp_app

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
    from pydantic import AnyUrl
    from mcpgateway.transports.streamablehttp_transport import read_resource, resource_service, user_context_var, mcp_app

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
    from mcpgateway.transports.streamablehttp_transport import list_prompts, server_id_var, prompt_service, user_context_var

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
    from mcpgateway.transports.streamablehttp_transport import list_resources, server_id_var, resource_service, user_context_var

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
    from mcpgateway.transports.streamablehttp_transport import (
        call_tool,
        request_headers_var,
        user_context_var,
        types,
    )

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)

    # Set request headers with a session id
    h_token = request_headers_var.set({"mcp-session-id": "abc-123-valid-session"})
    u_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})

    mock_pool = MagicMock()
    mock_pool.forward_request_to_owner = AsyncMock(
        return_value={"result": {"content": [{"type": "text", "text": "forwarded result"}]}}
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
        assert result[0].text == "forwarded result"
    finally:
        request_headers_var.reset(h_token)
        user_context_var.reset(u_token)


@pytest.mark.asyncio
async def test_call_tool_session_affinity_forwarded_with_structured(monkeypatch):
    """Test call_tool returns tuple when forwarded response has structuredContent."""
    from mcpgateway.transports.streamablehttp_transport import (
        call_tool,
        request_headers_var,
        user_context_var,
    )

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)

    h_token = request_headers_var.set({"mcp-session-id": "abc-123-valid-session"})
    u_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})

    mock_pool = MagicMock()
    mock_pool.forward_request_to_owner = AsyncMock(
        return_value={"result": {"content": [{"type": "text", "text": "r"}], "structuredContent": {"key": "val"}}}
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
        assert isinstance(result, tuple)
        assert result[1] == {"key": "val"}
    finally:
        request_headers_var.reset(h_token)
        user_context_var.reset(u_token)


@pytest.mark.asyncio
async def test_call_tool_session_affinity_forwarded_error(monkeypatch):
    """Test call_tool raises when forwarded response contains an error."""
    from mcpgateway.transports.streamablehttp_transport import (
        call_tool,
        request_headers_var,
        user_context_var,
    )

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)

    h_token = request_headers_var.set({"mcp-session-id": "abc-123-valid-session"})
    u_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})

    mock_pool = MagicMock()
    mock_pool.forward_request_to_owner = AsyncMock(
        return_value={"error": {"message": "remote error"}}
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
    from mcpgateway.transports.streamablehttp_transport import (
        call_tool,
        request_headers_var,
        user_context_var,
        types,
    )

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)

    h_token = request_headers_var.set({"mcp-session-id": "abc-123-valid-session"})
    u_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})

    mock_pool = MagicMock()
    mock_pool.forward_request_to_owner = AsyncMock(
        return_value={"result": {"content": [{"type": "image", "data": "abc", "mimeType": "image/png"}]}}
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
        assert isinstance(result[0], types.ImageContent)
    finally:
        request_headers_var.reset(h_token)
        user_context_var.reset(u_token)


@pytest.mark.asyncio
async def test_call_tool_session_affinity_rehydrate_audio(monkeypatch):
    """Test _rehydrate_content_items converts audio items."""
    from mcpgateway.transports.streamablehttp_transport import (
        call_tool,
        request_headers_var,
        user_context_var,
        types,
    )

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)

    h_token = request_headers_var.set({"mcp-session-id": "abc-123-valid-session"})
    u_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})

    mock_pool = MagicMock()
    mock_pool.forward_request_to_owner = AsyncMock(
        return_value={"result": {"content": [{"type": "audio", "data": "aud", "mimeType": "audio/mp3"}]}}
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
        assert isinstance(result[0], types.AudioContent)
    finally:
        request_headers_var.reset(h_token)
        user_context_var.reset(u_token)


@pytest.mark.asyncio
async def test_call_tool_session_affinity_rehydrate_unknown_and_invalid(monkeypatch):
    """Test _rehydrate_content_items handles unknown type and invalid (non-dict) items."""
    from mcpgateway.transports.streamablehttp_transport import (
        call_tool,
        request_headers_var,
        user_context_var,
        types,
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
    from mcpgateway.transports.streamablehttp_transport import (
        call_tool,
        tool_service,
        request_headers_var,
        user_context_var,
        types,
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
    from mcpgateway.transports.streamablehttp_transport import (
        call_tool,
        tool_service,
        request_headers_var,
        user_context_var,
        types,
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
    from mcpgateway.transports.streamablehttp_transport import (
        call_tool,
        request_headers_var,
        user_context_var,
        types,
    )

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcpgateway_session_affinity_enabled", True)

    h_token = request_headers_var.set({"mcp-session-id": "abc-123-valid-session"})
    u_token = user_context_var.set({"email": "user@test.com", "teams": ["t1"], "is_admin": False})

    mock_pool = MagicMock()
    mock_pool.forward_request_to_owner = AsyncMock(
        return_value={"result": {"content": [{"type": "text", "text": "ok"}]}}
    )
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
    from mcpgateway.transports.streamablehttp_transport import call_tool, request_headers_var, user_context_var, types

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
    from mcpgateway.transports.streamablehttp_transport import call_tool, request_headers_var, user_context_var, types

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
    from mcpgateway.transports.streamablehttp_transport import call_tool, tool_service, request_headers_var, user_context_var, types

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
    from mcpgateway.transports.streamablehttp_transport import call_tool, request_headers_var, user_context_var, types

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
            await send_func({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"mcp-session-id", b"new-session-id")],
            })
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
            await send_func({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"mcp-session-id", b"new-session-id")],
            })
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
        from mcp import types as mcp_types

        mock_gateway = MagicMock()
        mock_gateway.id = "gw-direct"
        mock_gateway.gateway_mode = "direct_proxy"

        mock_db = MagicMock()
        mock_db.execute = MagicMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway))
        )

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
        from mcp import types as mcp_types

        mock_gateway = MagicMock()
        mock_gateway.id = "gw-direct"
        mock_gateway.gateway_mode = "direct_proxy"

        mock_db = MagicMock()
        mock_db.execute = MagicMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway))
        )

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
        from mcp import types as mcp_types

        mock_gateway = MagicMock()
        mock_gateway.id = "gw-direct"
        mock_gateway.gateway_mode = "direct_proxy"

        mock_db = MagicMock()
        mock_db.execute = MagicMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway))
        )

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
        mock_db.execute = MagicMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway))
        )

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
        mock_db.execute = MagicMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway))
        )

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
    from mcpgateway.transports.streamablehttp_transport import list_resources, server_id_var, request_headers_var, resource_service

    mock_gateway = MagicMock()
    mock_gateway.id = "gw-cache"
    mock_gateway.gateway_mode = "cache"

    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_gateway)))

    @asynccontextmanager
    async def mock_get_db():
        yield mock_db

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


@pytest.mark.asyncio
async def test_list_resources_direct_proxy_disabled_setting(monkeypatch):
    """Test list_resources when gateway is direct_proxy but setting is disabled."""
    from mcpgateway.transports.streamablehttp_transport import list_resources, server_id_var, request_headers_var, resource_service

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
    from mcpgateway.transports.streamablehttp_transport import list_resources, server_id_var, request_headers_var, resource_service

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

            with caplog.at_level("WARNING"):
                await list_resources()
                # Case-insensitive check or matching the exact log output
                assert "Gateway gw-missing specified in X-Context-Forge-Gateway-Id header not found" in caplog.text

    server_id_var.reset(server_token)
    request_headers_var.reset(headers_token)


@pytest.mark.asyncio
async def test_list_resources_direct_proxy_meta_lookup_error(monkeypatch):
    """Test list_resources in direct_proxy mode when request_context raises LookupError."""
    from mcpgateway.transports.streamablehttp_transport import list_resources, server_id_var, request_headers_var, mcp_app

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
                    type(mcp_app).request_context = property(lambda self: (_ for _ in ()).throw(LookupError("No context")))

                    try:
                        await list_resources()

                        # Verify called with meta=None
                        mock_proxy.assert_awaited_once()
                        args = mock_proxy.call_args[0]
                        # signature: (gateway, request_headers, user_context, meta)
                        assert args[3] is None
                    finally:
                         # Restore property (mocking cleaning handled by context but manual reset for safety)
                         type(mcp_app).request_context = property(lambda self: (_ for _ in ()).throw(LookupError))

    server_id_var.reset(server_token)
    request_headers_var.reset(headers_token)


# ---------------------------------------------------------------------------
# _get_request_context_or_default
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_request_context_no_request_object(monkeypatch, caplog):
    """Test _get_request_context_or_default when context exists but request is None (lines 985-986)."""
    from mcpgateway.transports.streamablehttp_transport import _get_request_context_or_default, mcp_app, server_id_var
    from unittest.mock import PropertyMock

    token = server_id_var.set("default_server_id")

    mock_ctx = MagicMock()
    mock_ctx.request = None

    try:
        with patch.object(type(mcp_app), "request_context", new_callable=PropertyMock, return_value=mock_ctx):
            with caplog.at_level("WARNING"):
                sid, headers, user = await _get_request_context_or_default()

                assert sid == "default_server_id"
                assert "No request object found in MCP context" in caplog.text
    finally:
        server_id_var.reset(token)


@pytest.mark.asyncio
async def test_get_request_context_stateful_success(monkeypatch):
    """Test _get_request_context_or_default success path with server_id and auth (lines 988-1010)."""
    from mcpgateway.transports.streamablehttp_transport import _get_request_context_or_default, mcp_app, server_id_var
    from unittest.mock import PropertyMock

    token = server_id_var.set("default_server_id")

    # Use a HEX server ID because the regex enforces [a-fA-F0-9\-]+
    valid_hex_id = "abc-123-def-456"

    mock_request = MagicMock()
    mock_request.url.path = f"/servers/{valid_hex_id}/mcp"
    mock_request.headers = {"authorization": "Bearer token"}
    mock_request.cookies = {}

    mock_ctx = MagicMock()
    mock_ctx.request = mock_request

    mock_auth_override = AsyncMock(return_value={"user": "test_user"})
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.require_auth_override", mock_auth_override)

    try:
        with patch.object(type(mcp_app), "request_context", new_callable=PropertyMock, return_value=mock_ctx):
            sid, headers, user = await _get_request_context_or_default()

            # Verify server_id extracted from URL
            assert sid == valid_hex_id
            assert headers["authorization"] == "Bearer token"
            assert user == {"user": "test_user"}
    finally:
        server_id_var.reset(token)


@pytest.mark.asyncio
async def test_get_request_context_auth_failure(monkeypatch, caplog):
    """Test _get_request_context_or_default handles auth exception (lines 1006-1008)."""
    from mcpgateway.transports.streamablehttp_transport import _get_request_context_or_default, mcp_app, server_id_var
    from unittest.mock import PropertyMock

    token = server_id_var.set("default_server_id")

    mock_request = MagicMock()
    mock_request.url.path = "/mcp" # No server ID
    mock_request.headers = {}
    mock_request.cookies = {}

    mock_ctx = MagicMock()
    mock_ctx.request = mock_request

    mock_auth_override = AsyncMock(side_effect=Exception("Auth failed"))
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.require_auth_override", mock_auth_override)

    try:
        with patch.object(type(mcp_app), "request_context", new_callable=PropertyMock, return_value=mock_ctx):
            with caplog.at_level("WARNING"):
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
    from mcpgateway.transports.streamablehttp_transport import SessionManagerWrapper
    import orjson

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


# ---------------------------------------------------------------------------
# streamable_http_auth exception fallbacks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_streamable_http_auth_verify_exception_fallback_permissive(monkeypatch):
    """Test auth exception fallback when permissive mode enabled and no proxy user."""
    from mcpgateway.transports.streamablehttp_transport import streamable_http_auth, user_context_var

    # Force verify_credentials to raise Exception
    monkeypatch.setattr(tr, "verify_credentials", AsyncMock(side_effect=Exception("Auth Service Down")))

    # Settings: Trust proxy is ON, but we won't provide header. Require auth is OFF (permissive).
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.trust_proxy_auth", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.proxy_user_header", "x-user")
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.mcp_require_auth", False)

    scope = _make_scope("/servers/abc-123/mcp", headers=[(b"authorization", b"Bearer bad-token")])
    sent = []

    async def send(msg):
        sent.append(msg)

    # Should catch exception, fail proxy check (no header), then succeed via permissive check
    result = await streamable_http_auth(scope, None, send)

    assert result is True
    assert sent == []

    ctx = user_context_var.get()
    assert ctx["is_authenticated"] is False
    assert ctx["teams"] == []
