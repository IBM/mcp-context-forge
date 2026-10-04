# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_mcp_client_chat_service_tool_source.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Tests for loading MCP tools as LangChain tools with the MCP SDK v2 client.
"""

# Third-Party
from mcp.server.mcpserver import MCPServer
import pytest

# First-Party
from mcpgateway.services import mcp_client_chat_service as svc

pytest.importorskip("langchain_core")


def _server() -> MCPServer:
    server = MCPServer("weather")

    @server.tool()
    def get_weather(city: str) -> str:
        """Return the weather for a city."""
        return f"sunny in {city}"

    @server.tool()
    def broken() -> str:
        """Always fails."""
        raise ValueError("station offline")

    return server


@pytest.fixture
def in_process_server(monkeypatch):
    server = _server()
    monkeypatch.setattr(svc, "_mcp_transport", lambda _connection: server)
    return server


@pytest.mark.asyncio
async def test_tool_source_lists_tools_with_their_schemas(in_process_server):
    tools = await svc._MCPToolSource({"default": {"transport": "streamable_http", "url": "http://unused"}}).get_tools()

    by_name = {tool.name: tool for tool in tools}
    assert set(by_name) == {"get_weather", "broken"}
    assert by_name["get_weather"].description == "Return the weather for a city."
    assert by_name["get_weather"].args["city"]["type"] == "string"


@pytest.mark.asyncio
async def test_tool_calls_the_mcp_tool(in_process_server):
    tools = await svc._MCPToolSource({"default": {"transport": "streamable_http", "url": "http://unused"}}).get_tools()
    weather = next(tool for tool in tools if tool.name == "get_weather")

    assert await weather.ainvoke({"city": "Prague"}) == "sunny in Prague"


@pytest.mark.asyncio
async def test_tool_error_is_raised_as_tool_exception(in_process_server):
    tools = await svc._MCPToolSource({"default": {"transport": "streamable_http", "url": "http://unused"}}).get_tools()
    broken = next(tool for tool in tools if tool.name == "broken")

    with pytest.raises(svc.ToolException, match="Error executing tool broken"):
        await broken.ainvoke({})


def test_transport_selection():
    assert svc._mcp_transport({"transport": "stdio", "command": "python", "args": ["s.py"]}).args == ["s.py"]
    with pytest.raises(ValueError, match="Unsupported MCP transport"):
        svc._mcp_transport({"transport": "websocket"})
