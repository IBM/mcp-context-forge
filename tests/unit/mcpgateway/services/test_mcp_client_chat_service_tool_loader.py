# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_mcp_client_chat_service_tool_loader.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for loading MCP tools for LLM Chat with the MCP SDK client.
"""

# Standard
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock

# Third-Party
import httpcore2
from httpcore2._backends.anyio import AnyIOBackend
import httpx2
from mcp.client.stdio import StdioServerParameters
from mcp.server.mcpserver import MCPServer
import mcp_types
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.services import mcp_client_chat_service as svc
from mcpgateway.services.http_client_service import get_httpx2_timeout
from mcpgateway.utils.ssrf_pinning import PinnedTarget, SniPinningTransport

needs_langchain = pytest.mark.skipif(not svc._LLMCHAT_AVAILABLE, reason="the llmchat extra is not installed")

# --------------------------------------------------------------------------- #
# TRANSPORT SELECTION AND RESULT TEXT
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_build_transport_stdio():
    params = await svc._build_transport({"transport": "stdio", "command": "python", "args": ["server.py"]})
    assert isinstance(params, StdioServerParameters)
    assert params.command == "python"
    assert params.args == ["server.py"]


@pytest.mark.asyncio
async def test_build_transport_stdio_without_args():
    assert (await svc._build_transport({"transport": "stdio", "command": "python"})).args == []


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["streamable_http", "sse"])
async def test_build_transport_http_returns_a_context_manager_without_connecting(transport):
    target = await svc._build_transport({"transport": transport, "url": "http://127.0.0.1:9/mcp", "headers": {"Authorization": "Bearer t"}})
    assert hasattr(target, "__aenter__")


@pytest.mark.asyncio
async def test_build_transport_rejects_unknown_transport():
    with pytest.raises(ValueError, match="Unsupported MCP transport: websocket"):
        await svc._build_transport({"transport": "websocket"})


# --------------------------------------------------------------------------- #
# OUTBOUND ADDRESS PINNING
# --------------------------------------------------------------------------- #

PUBLIC_IP = "93.184.216.34"
PINNED_TARGET = PinnedTarget(validated_url="http://mcp.example.test/mcp", hostname="mcp.example.test", original_authority="mcp.example.test", resolved_ips=(PUBLIC_IP,))


@pytest.fixture
def captured_factories(monkeypatch):
    """Record the httpx client factory that each HTTP transport receives."""
    factories = {}

    def _capture(name):
        def _transport(url, **kwargs):
            factories[name] = kwargs["httpx_client_factory"]
            return object()

        return _transport

    monkeypatch.setattr(svc, "streamable_http_client", _capture("streamable_http"))
    monkeypatch.setattr(svc, "sse_client", _capture("sse"))
    return factories


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["streamable_http", "sse"])
async def test_build_transport_pins_the_http_client_to_the_validated_address(monkeypatch, captured_factories, transport):
    calls = []

    async def _resolve(url, field_name):
        calls.append((url, field_name))
        return PINNED_TARGET

    monkeypatch.setattr(svc, "resolve_pinned_target", _resolve)

    await svc._build_transport({"transport": transport, "url": "http://mcp.example.test/mcp"})
    await svc._build_transport({"transport": transport, "url": "http://mcp.example.test/mcp"})

    assert calls == [("http://mcp.example.test/mcp", "MCP server URL")] * 2
    client = captured_factories[transport](headers={"X-Test": "1"}, timeout=httpx2.Timeout(5.0), auth=None)
    assert isinstance(client._transport, SniPinningTransport)
    assert client._transport._pinned_hosts == (PUBLIC_IP,)
    assert client.follow_redirects is False
    assert client.headers["X-Test"] == "1"


@pytest.mark.asyncio
async def test_build_transport_builds_a_plain_client_for_an_unpinned_target(monkeypatch, captured_factories):
    unpinned = PinnedTarget(validated_url="http://mcp.example.test/mcp", hostname="", original_authority="", resolved_ips=())

    async def _resolve(url, field_name):
        return unpinned

    monkeypatch.setattr(svc, "resolve_pinned_target", _resolve)

    await svc._build_transport({"transport": "streamable_http", "url": "http://mcp.example.test/mcp"})

    client = captured_factories["streamable_http"]()
    assert not isinstance(client._transport, SniPinningTransport)
    assert client.follow_redirects is False
    assert client.timeout == get_httpx2_timeout()


@pytest.fixture
def strict_ssrf(monkeypatch):
    """Turn on SSRF protection with no localhost or private-network exemption."""
    monkeypatch.setattr(settings, "ssrf_protection_enabled", True)
    monkeypatch.setattr(settings, "ssrf_allow_localhost", False)
    monkeypatch.setattr(settings, "ssrf_allow_private_networks", False)


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["streamable_http", "sse"])
@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.5", "169.254.169.254"])
async def test_build_transport_refuses_a_blocked_address(strict_ssrf, captured_factories, transport, address):
    with pytest.raises(ConnectionError, match="blocked by the outbound URL policy"):
        await svc._build_transport({"transport": transport, "url": f"http://{address}/mcp"})
    assert captured_factories == {}


@needs_langchain
@pytest.mark.asyncio
async def test_blocked_url_at_call_time_is_returned_to_the_model(strict_ssrf):
    tool = svc.MCPToolLoader({"transport": "sse", "url": "http://169.254.169.254/mcp"})._as_langchain_tool(mcp_types.Tool(name="t", inputSchema={"type": "object", "properties": {}}))

    assert "blocked by the outbound URL policy" in await tool.ainvoke({})


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["streamable_http", "sse"])
async def test_tool_loader_dials_only_the_address_that_passed_validation(monkeypatch, strict_ssrf, transport):
    """A name that resolves to a public address at validation and to loopback later must not reach loopback."""
    for name in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(name, raising=False)

    real_getaddrinfo = socket.getaddrinfo
    answers = iter([PUBLIC_IP])

    def _changing_dns(host, port=None, *args, **kwargs):
        if host in ("mcp.example.test", b"mcp.example.test"):
            ip = next(answers, "127.0.0.1")
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 0))]
        return real_getaddrinfo(host, port, *args, **kwargs)

    dialed = []

    async def _refuse_dial(self, host, port, *args, **kwargs):
        dialed.append(host)
        raise httpcore2.ConnectError("dial refused by test")

    monkeypatch.setattr(socket, "getaddrinfo", _changing_dns)
    monkeypatch.setattr(AnyIOBackend, "connect_tcp", _refuse_dial)

    # streamable_http wraps the dial error in a task-group ExceptionGroup; sse raises it bare
    with pytest.RaisesGroup(httpx2.ConnectError, allow_unwrapped=True):
        await svc.MCPToolLoader({"transport": transport, "url": "http://mcp.example.test/mcp"}).list_tools()

    assert dialed and set(dialed) == {PUBLIC_IP}


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
    monkeypatch.setattr(svc, "_build_transport", AsyncMock(return_value=server))
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

    monkeypatch.setattr(svc, "_build_transport", AsyncMock(return_value=object()))
    monkeypatch.setattr(svc, "MCPSDKClient", _FakeClient)

    tools = await svc.MCPToolLoader({"transport": "sse", "url": "http://unused"}).list_tools()

    assert [tool.name for tool in tools] == ["first", "second"]
    assert seen == [None, "p2"]


# --------------------------------------------------------------------------- #
# WRAPPING FOR LANGCHAIN (runs only where the llmchat extra is installed)
# --------------------------------------------------------------------------- #


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
