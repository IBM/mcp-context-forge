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

    # Mock settings to enable stateful sessions
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.use_stateful_sessions", True)
    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.settings.json_response_enabled", False)
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
async def test_session_manager_wrapper_handle_streamable_http_no_server_id(monkeypatch):
    """Test handle_streamable_http without server_id match in path."""
    # Standard
    from contextlib import asynccontextmanager

    # First-Party
    from mcpgateway.transports.streamablehttp_transport import server_id_var

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
            # Check that server_id was set to None
            assert server_id_var.get() is None
            await send_func("ok_no_server")

    monkeypatch.setattr(tr, "StreamableHTTPSessionManager", lambda **kwargs: DummySessionManager())
    wrapper = SessionManagerWrapper()
    await wrapper.initialize()
    # Use a path that doesn't match the server_id pattern
    scope = _make_scope("/some/other/path")
    sent = []
    await wrapper.handle_streamable_http(scope, None, send)
    await wrapper.shutdown()
    assert sent == ["ok_no_server"]


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
    assert user_ctx.get("teams") is None  # None = unrestricted (legacy token without teams key)


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
    assert user_ctx.get("teams") is None  # None = teams: null treated same as missing


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
