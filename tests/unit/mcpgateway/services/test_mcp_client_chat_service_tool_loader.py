# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_mcp_client_chat_service_tool_loader.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for loading MCP tools as LangChain tools with the MCP SDK client.
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
# TRANSPORT SELECTION (no LangChain needed)
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
# TOOL LOADER AGAINST AN IN-PROCESS MCP SERVER
# --------------------------------------------------------------------------- #

langchain_core = pytest.importorskip("langchain_core")


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
async def test_loader_lists_tools_with_their_schemas(loader):
    tools = {tool.name: tool for tool in await loader.get_tools()}

    assert set(tools) == {"echo", "fail"}
    assert tools["echo"].description == "Repeat the text."
    assert tools["echo"].args["text"]["type"] == "string"
    assert tools["echo"].args["times"]["type"] == "integer"


@pytest.mark.asyncio
async def test_loader_tool_calls_the_mcp_tool(loader):
    echo = next(tool for tool in await loader.get_tools() if tool.name == "echo")

    assert await echo.ainvoke({"text": "ab", "times": 2}) == "abab"


@pytest.mark.asyncio
async def test_loader_tool_error_result_raises_tool_exception(loader):
    fail = next(tool for tool in await loader.get_tools() if tool.name == "fail")

    with pytest.raises(svc.ToolException, match="fail"):
        await fail.ainvoke({})


@pytest.mark.asyncio
async def test_loader_follows_pagination(monkeypatch):
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

    tools = await svc.MCPToolLoader({"transport": "sse", "url": "http://unused"}).get_tools()

    assert [tool.name for tool in tools] == ["first", "second"]
    assert seen == [None, "p2"]
