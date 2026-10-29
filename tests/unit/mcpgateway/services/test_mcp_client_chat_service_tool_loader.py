# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_mcp_client_chat_service_tool_loader.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for loading MCP tools for LLM Chat with the MCP SDK client.
"""

# Standard
from types import SimpleNamespace

# Third-Party
from mcp.client.stdio import StdioServerParameters
from mcp.server.mcpserver import MCPServer
import mcp_types
import pytest

# First-Party
from mcpgateway.services import mcp_client_chat_service as svc

# --------------------------------------------------------------------------- #
# TRANSPORT SELECTION AND RESULT TEXT
# --------------------------------------------------------------------------- #


def test_build_transport_stdio():
    params = svc._build_transport({"transport": "stdio", "command": "python", "args": ["server.py"]})
    assert isinstance(params, StdioServerParameters)
    assert params.command == "python"
    assert params.args == ["server.py"]


def test_build_transport_stdio_without_args():
    assert svc._build_transport({"transport": "stdio", "command": "python"}).args == []


@pytest.mark.parametrize("transport", ["streamable_http", "sse"])
def test_build_transport_http_returns_a_context_manager_without_connecting(transport):
    target = svc._build_transport({"transport": transport, "url": "http://127.0.0.1:9/mcp", "headers": {"Authorization": "Bearer t"}})
    assert hasattr(target, "__aenter__")


def test_build_transport_rejects_unknown_transport():
    with pytest.raises(ValueError, match="Unsupported MCP transport: websocket"):
        svc._build_transport({"transport": "websocket"})


def test_result_text_joins_text_blocks_only():
    result = mcp_types.CallToolResult(
        content=[
            mcp_types.TextContent(type="text", text="one"),
            mcp_types.ImageContent(type="image", data="aGk=", mimeType="image/png"),
            mcp_types.TextContent(type="text", text="two"),
        ]
    )
    assert svc._result_text(result) == "one\ntwo"


# --------------------------------------------------------------------------- #
# TALKING TO AN IN-PROCESS MCP SERVER (no LangChain needed)
# --------------------------------------------------------------------------- #


def _server() -> MCPServer:
    server = MCPServer("chat-tools")

    @server.tool()
    def echo(text: str, times: int = 1) -> str:
        """Repeat the text."""
        return text * times

    @server.tool()
    def fail() -> str:
        """Always fails."""
        raise ValueError("station offline")

    return server


@pytest.fixture
def loader(monkeypatch):
    server = _server()
    monkeypatch.setattr(svc, "_build_transport", lambda _connection: server)
    return svc.MCPToolLoader({"transport": "streamable_http", "url": "http://unused"})


@pytest.mark.asyncio
async def test_list_tools_returns_the_server_definitions(loader):
    tools = {tool.name: tool for tool in await loader.list_tools()}

    assert set(tools) == {"echo", "fail"}
    assert tools["echo"].description == "Repeat the text."
    assert tools["echo"].input_schema["properties"]["text"]["type"] == "string"
    assert tools["echo"].input_schema["properties"]["times"]["type"] == "integer"


@pytest.mark.asyncio
async def test_call_tool_returns_the_text_content(loader):
    assert await loader.call_tool("echo", {"text": "ab", "times": 2}) == ("abab", False)


@pytest.mark.asyncio
async def test_call_tool_reports_an_error_result(loader):
    text, is_error = await loader.call_tool("fail", {})

    assert is_error is True
    assert "fail" in text


@pytest.mark.asyncio
async def test_list_tools_follows_pagination(monkeypatch):
    pages = {
        None: SimpleNamespace(tools=[mcp_types.Tool(name="first", inputSchema={"type": "object", "properties": {}})], next_cursor="p2"),
        "p2": SimpleNamespace(tools=[mcp_types.Tool(name="second", inputSchema={"type": "object", "properties": {}})], next_cursor=None),
    }
    seen = []

    class _FakeClient:
        def __init__(self, _target):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def list_tools(self, *, cursor=None):
            seen.append(cursor)
            return pages[cursor]

    monkeypatch.setattr(svc, "_build_transport", lambda _connection: object())
    monkeypatch.setattr(svc, "MCPSDKClient", _FakeClient)

    tools = await svc.MCPToolLoader({"transport": "sse", "url": "http://unused"}).list_tools()

    assert [tool.name for tool in tools] == ["first", "second"]
    assert seen == [None, "p2"]


# --------------------------------------------------------------------------- #
# WRAPPING FOR LANGCHAIN (runs only where the llmchat extra is installed)
# --------------------------------------------------------------------------- #

needs_langchain = pytest.mark.skipif(not svc._LLMCHAT_AVAILABLE, reason="the llmchat extra is not installed")


@needs_langchain
@pytest.mark.asyncio
async def test_get_tools_wraps_each_tool_for_langchain(loader):
    tools = {tool.name: tool for tool in await loader.get_tools()}

    assert set(tools) == {"echo", "fail"}
    assert tools["echo"].description == "Repeat the text."
    assert tools["echo"].args["text"]["type"] == "string"
    assert await tools["echo"].ainvoke({"text": "ab", "times": 2}) == "abab"
    # An error result comes back as text for the model instead of aborting the run
    assert "fail" in await tools["fail"].ainvoke({})


@needs_langchain
@pytest.mark.asyncio
async def test_agent_run_survives_a_failing_tool(loader):
    """The agent loop hands a tool error back to the model as a tool message instead of aborting the turn."""
    # Third-Party
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    class _ScriptedModel(FakeMessagesListChatModel):
        """Scripted answers; the fake base class does not implement bind_tools."""

        def bind_tools(self, tools, **_kwargs):
            return self

    model = _ScriptedModel(responses=[AIMessage(content="", tool_calls=[{"name": "fail", "args": {}, "id": "call-1"}]), AIMessage(content="The tool failed.")])
    agent = svc.create_react_agent(model, await loader.get_tools())

    result = await agent.ainvoke({"messages": [HumanMessage(content="run fail")]})

    tool_messages = [message for message in result["messages"] if isinstance(message, ToolMessage)]
    assert len(tool_messages) == 1
    assert "fail" in tool_messages[0].content
    assert result["messages"][-1].content == "The tool failed."
