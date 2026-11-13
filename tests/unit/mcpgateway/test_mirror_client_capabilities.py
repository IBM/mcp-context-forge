# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_mirror_client_capabilities.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

The gateway advertises the end client's elicitation support upstream, and refuses
to relay a question the client never declared support for.
"""

# Future
from __future__ import annotations

# Standard
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Annotated
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

# Third-Party
from mcp import Client
from mcp.client.session import _make_handshake_stamp, _make_modern_stamp
from mcp.server.mcpserver import Elicit, MCPServer, Resolve
from mcp.shared.exceptions import MCPError
import mcp_types as types
from mcp_types import CLIENT_CAPABILITIES_META_KEY
from pydantic import BaseModel, TypeAdapter
import pytest

# First-Party
from mcpgateway.services.prompt_service import PromptInputRequired
from mcpgateway.services.resource_service import ResourceInputRequired
from mcpgateway.services.tool_service import ToolInputRequired
from mcpgateway.transports import streamablehttp_transport as tr
from mcpgateway.utils import mcp_proxy_client as proxy

MODERN = "2026-07-28"
LEGACY = "2025-11-25"
FORM_ONLY = types.ClientCapabilities(elicitation=types.ElicitationCapability(form=types.FormElicitationCapability()))
URL_ONLY = types.ClientCapabilities(elicitation=types.ElicitationCapability(url=types.UrlElicitationCapability()))


def _form_question(key: str) -> types.InputRequiredResult:
    request = types.ElicitRequest(params=types.ElicitRequestFormParams(message=f"{key}?", requestedSchema={"type": "object", "properties": {key: {"type": "string"}}}))
    return types.InputRequiredResult(inputRequests={key: request}, requestState="sealed")


def _url_question() -> types.InputRequiredResult:
    request = types.ElicitRequest(params=types.ElicitRequestURLParams(mode="url", message="Open the link", url="https://example.test/approve", elicitationId="approve-1"))
    return types.InputRequiredResult(inputRequests={"approval": request}, requestState="sealed")


# --------------------------------------------------------------------------- #
# PROXY CLIENT: the SDK stamp keeps the caller's elicitation support
# --------------------------------------------------------------------------- #


def _hooked_session(stamp) -> SimpleNamespace:
    client = SimpleNamespace(session=SimpleNamespace(_stamp=stamp))
    proxy.keep_caller_capabilities(client)
    return client.session


def _modern_request(caller_meta: dict | None) -> dict:
    meta = dict(caller_meta or {})
    return {"jsonrpc": "2.0", "id": 1, "method": "prompts/get", "params": {"name": "p", "_meta": meta}}


def test_modern_stamp_keeps_the_callers_question_capabilities_and_drops_extensions():
    session = _hooked_session(_make_modern_stamp(MODERN, {"name": "gw", "version": "1"}, {}, lambda _name, _args: {}))
    declared = {"elicitation": {"form": {}, "url": {}}, "sampling": {"tools": {}}, "roots": {"listChanged": True}, "extensions": {"x": {}}}
    data = _modern_request({CLIENT_CAPABILITIES_META_KEY: declared, "traceparent": "00-abc"})

    session._stamp(data, {})

    meta = data["params"]["_meta"]
    assert meta[CLIENT_CAPABILITIES_META_KEY] == {"elicitation": {"form": {}, "url": {}}, "sampling": {"tools": {}}, "roots": {"listChanged": True}}
    assert meta["io.modelcontextprotocol/protocolVersion"] == MODERN
    assert meta["traceparent"] == "00-abc"


def test_modern_stamp_sends_the_gateways_own_set_when_the_caller_declared_none():
    session = _hooked_session(_make_modern_stamp(MODERN, {"name": "gw", "version": "1"}, {}, lambda _name, _args: {}))
    data = _modern_request({"traceparent": "00-abc"})

    session._stamp(data, {})

    assert data["params"]["_meta"][CLIENT_CAPABILITIES_META_KEY] == {}


def test_handshake_stamp_is_left_alone_for_a_legacy_upstream():
    session = _hooked_session(_make_handshake_stamp(LEGACY))
    data = _modern_request({CLIENT_CAPABILITIES_META_KEY: {"elicitation": {"form": {}}}})
    before = dict(data["params"]["_meta"])

    session._stamp(data, {})

    assert data["params"]["_meta"] == before


# --------------------------------------------------------------------------- #
# END TO END: a strict SDK upstream only asks when the caller declared support
# --------------------------------------------------------------------------- #


class Name(BaseModel):
    name: str


def _ask_name() -> Elicit[Name]:
    return Elicit("Your name?", Name)


def _strict_upstream() -> MCPServer:
    """An upstream whose tool asks through the SDK resolver path, which enforces the capability gate."""
    server = MCPServer("strict-upstream")

    @server.tool()
    def greet(who: Annotated[Name, Resolve(_ask_name)]) -> str:
        """Greets once it knows a name."""
        return f"hello {who.name}"

    return server


_CALL_TOOL_RESULT = TypeAdapter(types.CallToolResult | types.InputRequiredResult)


async def _call_greet(client: Client, caller_meta: dict | None) -> types.CallToolResult | types.InputRequiredResult:
    params = {"name": "greet", "arguments": {}}
    if caller_meta is not None:
        params["_meta"] = caller_meta
    request = types.CallToolRequest(params=types.CallToolRequestParams.model_validate(params))
    return await client.session.send_request(request, _CALL_TOOL_RESULT)


@pytest.fixture
def in_process_upstream(monkeypatch):
    """Point both transport factories at the strict upstream; the real SDK Client wraps it."""
    upstream = _strict_upstream()
    monkeypatch.setattr(proxy, "streamable_http_client", lambda _url, http_client=None: upstream)
    monkeypatch.setattr(proxy, "sse_client", lambda _url, **_kwargs: upstream)


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["streamablehttp", "sse"])
async def test_strict_upstream_asks_when_the_gateway_relays_the_callers_support(in_process_upstream, transport):
    async with proxy.mcp_proxy_client("http://upstream.test/mcp", transport=transport, mode=MODERN) as client:
        result = await _call_greet(client, {CLIENT_CAPABILITIES_META_KEY: {"elicitation": {"form": {}}}})

    assert isinstance(result, types.InputRequiredResult)
    assert result.input_requests and next(iter(result.input_requests.values())).params.message == "Your name?"


@pytest.mark.asyncio
async def test_strict_upstream_refuses_when_the_caller_declared_nothing(in_process_upstream):
    async with proxy.mcp_proxy_client("http://upstream.test/mcp", mode=MODERN) as client:
        with pytest.raises(MCPError) as exc_info:
            await _call_greet(client, {CLIENT_CAPABILITIES_META_KEY: {}})

    assert exc_info.value.error.code == types.MISSING_REQUIRED_CLIENT_CAPABILITY


@pytest.mark.asyncio
async def test_strict_upstream_refuses_without_the_hook_even_for_a_capable_caller():
    """The gateway's own client advertises nothing, so without the hook the upstream never asks."""
    async with Client(_strict_upstream(), mode=MODERN) as client:
        with pytest.raises(MCPError) as exc_info:
            await _call_greet(client, {CLIENT_CAPABILITIES_META_KEY: {"elicitation": {"form": {}}}})

    assert exc_info.value.error.code == types.MISSING_REQUIRED_CLIENT_CAPABILITY


# --------------------------------------------------------------------------- #
# TRANSPORT: a question the caller cannot answer is refused with -32021
# --------------------------------------------------------------------------- #


@pytest.fixture
def fake_db(monkeypatch):
    @asynccontextmanager
    async def fake_get_db():
        yield MagicMock()

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)


def _request_context(version: str, declared: types.ClientCapabilities | None) -> MagicMock:
    ctx = MagicMock()
    ctx.meta = None
    ctx.protocol_version = version
    ctx.params = {}
    ctx.session.client_capabilities = declared
    return ctx


def _required(exc_info) -> dict:
    assert exc_info.value.error.code == types.MISSING_REQUIRED_CLIENT_CAPABILITY
    return exc_info.value.error.data["requiredCapabilities"]


@pytest.mark.asyncio
async def test_prompt_handler_refuses_a_form_question_for_a_caller_without_elicitation(fake_db, monkeypatch):
    monkeypatch.setattr(tr.prompt_service, "get_prompt", AsyncMock(side_effect=PromptInputRequired(_form_question("name"))))
    with patch.object(type(tr.mcp_app), "request_context", new_callable=PropertyMock, return_value=_request_context(MODERN, None)):
        with pytest.raises(MCPError) as exc_info:
            await tr.get_prompt("up-needs-input", {})
    assert _required(exc_info) == {"elicitation": {"form": {}}}


@pytest.mark.asyncio
async def test_prompt_handler_refuses_a_url_question_for_a_form_only_caller(fake_db, monkeypatch):
    monkeypatch.setattr(tr.prompt_service, "get_prompt", AsyncMock(side_effect=PromptInputRequired(_url_question())))
    with patch.object(type(tr.mcp_app), "request_context", new_callable=PropertyMock, return_value=_request_context(MODERN, FORM_ONLY)):
        with pytest.raises(MCPError) as exc_info:
            await tr.get_prompt("up-needs-link", {})
    assert _required(exc_info) == {"elicitation": {"url": {}}}


@pytest.mark.asyncio
async def test_prompt_handler_relays_a_url_question_to_a_url_capable_caller(fake_db, monkeypatch):
    question = _url_question()
    monkeypatch.setattr(tr.prompt_service, "get_prompt", AsyncMock(side_effect=PromptInputRequired(question)))
    with patch.object(type(tr.mcp_app), "request_context", new_callable=PropertyMock, return_value=_request_context(MODERN, URL_ONLY)):
        assert await tr.get_prompt("up-needs-link", {}) is question


@pytest.mark.asyncio
async def test_resource_handler_refuses_a_form_question_for_a_url_only_caller(fake_db, monkeypatch):
    monkeypatch.setattr(tr.resource_service, "read_resource", AsyncMock(side_effect=ResourceInputRequired(_form_question("pin"))))
    with patch.object(type(tr.mcp_app), "request_context", new_callable=PropertyMock, return_value=_request_context(MODERN, URL_ONLY)):
        with pytest.raises(MCPError) as exc_info:
            await tr.read_resource("vault://bob")
    assert _required(exc_info) == {"elicitation": {"form": {}}}


@pytest.mark.asyncio
async def test_tool_handler_refuses_a_form_question_for_a_caller_without_elicitation(fake_db, monkeypatch):
    monkeypatch.setattr(tr.tool_service, "invoke_tool", AsyncMock(side_effect=ToolInputRequired(_form_question("colour"))))
    with patch.object(type(tr.mcp_app), "request_context", new_callable=PropertyMock, return_value=_request_context(MODERN, None)):
        with pytest.raises(MCPError) as exc_info:
            await tr.call_tool("asking_tool", {})
    assert _required(exc_info) == {"elicitation": {"form": {}}}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("declared", "required"),
    [
        (None, {"sampling": {}}),
        (types.ClientCapabilities(sampling=types.SamplingCapability()), None),
    ],
)
async def test_tool_handler_judges_a_sampling_question_by_the_declared_sampling_support(fake_db, monkeypatch, declared, required):
    sample = types.CreateMessageRequest(params=types.CreateMessageRequestParams(messages=[], maxTokens=1))
    question = types.InputRequiredResult(inputRequests={"s": sample}, requestState="sealed")
    monkeypatch.setattr(tr.tool_service, "invoke_tool", AsyncMock(side_effect=ToolInputRequired(question)))
    with patch.object(type(tr.mcp_app), "request_context", new_callable=PropertyMock, return_value=_request_context(MODERN, declared)):
        if required is None:
            assert await tr.call_tool("asking_tool", {}) is question
        else:
            with pytest.raises(MCPError) as exc_info:
                await tr.call_tool("asking_tool", {})
            assert _required(exc_info) == required


@pytest.mark.asyncio
async def test_tool_handler_requires_sampling_tools_for_a_sampling_question_that_carries_tools(fake_db, monkeypatch):
    tool = types.Tool(name="t", inputSchema={"type": "object"})
    sample = types.CreateMessageRequest(params=types.CreateMessageRequestParams(messages=[], maxTokens=1, tools=[tool]))
    question = types.InputRequiredResult(inputRequests={"s": sample}, requestState="sealed")
    monkeypatch.setattr(tr.tool_service, "invoke_tool", AsyncMock(side_effect=ToolInputRequired(question)))
    with patch.object(type(tr.mcp_app), "request_context", new_callable=PropertyMock, return_value=_request_context(MODERN, types.ClientCapabilities(sampling=types.SamplingCapability()))):
        with pytest.raises(MCPError) as exc_info:
            await tr.call_tool("asking_tool", {})
    assert _required(exc_info) == {"sampling": {"tools": {}}}


@pytest.mark.asyncio
async def test_resource_handler_refuses_a_roots_question_for_a_caller_without_roots(fake_db, monkeypatch):
    question = types.InputRequiredResult(inputRequests={"r": types.ListRootsRequest()}, requestState="sealed")
    monkeypatch.setattr(tr.resource_service, "read_resource", AsyncMock(side_effect=ResourceInputRequired(question)))
    with patch.object(type(tr.mcp_app), "request_context", new_callable=PropertyMock, return_value=_request_context(MODERN, FORM_ONLY)):
        with pytest.raises(MCPError) as exc_info:
            await tr.read_resource("vault://bob")
    assert _required(exc_info) == {"roots": {}}
