# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_mrtr_prompts_resources.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Unit tests for 2026 multi-round-trip pass-through on prompts/get and resources/read (#6641).

An in-process SDK server plays the upstream: its prompt asks two questions before it renders,
and its resource asks one before it serves. The gateway must relay each question to a modern
caller untouched, thread the caller's answers back, and refuse a legacy caller cleanly.
"""

# Standard
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

# Third-Party
from mcp import Client
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.prompts.base import UserMessage
from mcp.shared.exceptions import MCPError
import mcp_types as types
import pytest

# First-Party
from mcpgateway.services import prompt_service as ps
from mcpgateway.services import resource_service as rs
from mcpgateway.services.prompt_service import PromptInputRequired, PromptService
from mcpgateway.services.resource_service import ResourceInputRequired
from mcpgateway.transports import streamablehttp_transport as tr

MODERN = "2026-07-28"
LEGACY = "2025-11-25"


def _question(key: str, prompt_text: str, state: str) -> types.InputRequiredResult:
    request = types.ElicitRequest(params=types.ElicitRequestFormParams(message=prompt_text, requestedSchema={"type": "object", "properties": {key: {"type": "string"}}}))
    return types.InputRequiredResult(inputRequests={key: request}, requestState=state)


def _answer(**content) -> types.ElicitResult:
    return types.ElicitResult(action="accept", content=content)


def _upstream() -> MCPServer:
    """An upstream whose prompt needs two rounds of input and whose resource needs one."""
    server = MCPServer("mrtr-upstream")

    @server.prompt()
    def needs_input(ctx: Context) -> list | types.InputRequiredResult:
        """Greets once it knows a name and a colour."""
        answers = ctx.input_responses or {}
        if ctx.request_state is None:
            return _question("name", "Your name?", "asked-name")
        if ctx.request_state == "asked-name":
            return _question("colour", "Your colour?", "asked-colour:" + answers["name"].content["name"])
        name = ctx.request_state.split(":", 1)[1]
        return [UserMessage(content=types.TextContent(type="text", text=f"hello {name} in {answers['colour'].content['colour']}"))]

    @server.resource("vault://{name}")
    def vault(name: str, ctx: Context) -> str | types.InputRequiredResult:
        """Serves a secret once it has a pin."""
        if ctx.request_state is None:
            return _question("pin", "Pin?", "asked-pin")
        return f"secret for {name}: {ctx.input_responses['pin'].content['pin']}"

    return server


@pytest.fixture
def upstream():
    return _upstream()


@pytest.fixture
def in_process_proxy(upstream, monkeypatch):
    """Point both services' per-call proxy client at the in-process upstream."""

    @asynccontextmanager
    async def fake_proxy_client(**_kwargs):
        async with Client(upstream, mode=MODERN) as client:
            yield client

    monkeypatch.setattr(ps, "mcp_proxy_client", fake_proxy_client)
    monkeypatch.setattr(rs, "mcp_proxy_client", fake_proxy_client)
    monkeypatch.setattr(ps, "_downstream_session_id_from_request", lambda: None)
    monkeypatch.setattr(ps, "build_gateway_auth_headers", lambda _gateway: {})


def _gateway_prompt(transport: str = "streamable_http") -> SimpleNamespace:
    gateway = SimpleNamespace(id="gw-1", url="http://upstream.test/mcp", transport=transport, auth_type=None, auth_query_params=None)
    return SimpleNamespace(name="up-needs-input", original_name="needs_input", description="relayed", gateway=gateway)


# --------------------------------------------------------------------------- #
# PROMPT SERVICE: real rounds against the in-process upstream
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_prompt_fetch_relays_each_question_and_renders_after_three_rounds(in_process_proxy):
    service = PromptService()
    prompt = _gateway_prompt()

    with pytest.raises(PromptInputRequired) as first:
        await service._fetch_gateway_prompt_result(prompt, None)
    assert set(first.value.result.input_requests) == {"name"}
    assert first.value.result.input_requests["name"].params.message == "Your name?"

    with pytest.raises(PromptInputRequired) as second:
        await service._fetch_gateway_prompt_result(prompt, None, input_responses={"name": _answer(name="madhu")}, request_state=first.value.result.request_state)
    assert set(second.value.result.input_requests) == {"colour"}

    final = await service._fetch_gateway_prompt_result(prompt, None, input_responses={"colour": _answer(colour="blue")}, request_state=second.value.result.request_state)
    assert final.messages[0].content.text == "hello madhu in blue"


@pytest.mark.asyncio
async def test_prompt_fetch_relays_a_question_on_the_sse_branch(in_process_proxy):
    """The SSE per-call branch threads the retry fields and raises the same signal."""
    service = PromptService()
    prompt = _gateway_prompt(transport="sse")

    with pytest.raises(PromptInputRequired) as first:
        await service._fetch_gateway_prompt_result(prompt, None)
    with pytest.raises(PromptInputRequired) as second:
        await service._fetch_gateway_prompt_result(prompt, None, input_responses={"name": _answer(name="x")}, request_state=first.value.result.request_state)
    final = await service._fetch_gateway_prompt_result(prompt, None, input_responses={"colour": _answer(colour="red")}, request_state=second.value.result.request_state)
    assert final.messages[0].content.text == "hello x in red"


@pytest.mark.asyncio
async def test_prompt_fetch_threads_retry_fields_on_the_pooled_branch(monkeypatch):
    """The pooled-session branch passes the answers and state to the upstream helper."""
    captured = {}

    async def fake_helper(session, name, arguments, meta_data, progress_callback=None, input_responses=None, request_state=None):
        captured.update(name=name, input_responses=input_responses, request_state=request_state)
        return types.GetPromptResult(messages=[])

    class _Acquire:
        async def __aenter__(self):
            return SimpleNamespace(session=MagicMock())

        async def __aexit__(self, *_exc):
            return False

    registry = MagicMock()
    registry.acquire = MagicMock(return_value=_Acquire())
    monkeypatch.setattr(ps, "_downstream_session_id_from_request", lambda: "downstream-1")
    monkeypatch.setattr(ps, "get_upstream_session_registry", lambda: registry)
    monkeypatch.setattr(ps, "build_gateway_auth_headers", lambda _gateway: {})
    monkeypatch.setattr(ps, "_get_prompt_with_meta", fake_helper)

    await PromptService()._fetch_gateway_prompt_result(_gateway_prompt(), None, input_responses={"name": _answer(name="m")}, request_state="sealed")

    assert captured["name"] == "needs_input"
    assert captured["request_state"] == "sealed"
    assert captured["input_responses"]["name"].content == {"name": "m"}


def test_prompt_request_builder_carries_the_retry_fields():
    request = ps._build_get_prompt_request("needs_input", None, None, {"name": _answer(name="m")}, "sealed")
    wire = request.model_dump(by_alias=True, exclude_none=True)["params"]
    assert wire["requestState"] == "sealed"
    assert wire["inputResponses"]["name"]["content"] == {"name": "m"}
    assert "_meta" not in wire


# --------------------------------------------------------------------------- #
# RESOURCE SERVICE: real rounds against the in-process upstream
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_resource_read_helper_relays_the_question_and_serves_after_the_answer(upstream):
    async with Client(upstream, mode=MODERN) as client:
        first = await rs._read_resource_with_meta(client.session, "vault://bob", None)
        with pytest.raises(ResourceInputRequired) as signal:
            rs._raise_if_input_required(first)
        assert set(signal.value.result.input_requests) == {"pin"}

        served = await rs._read_resource_with_meta(client.session, "vault://bob", None, input_responses={"pin": _answer(pin="4242")}, request_state=first.request_state)
        rs._raise_if_input_required(served)
        assert served.contents[0].text == "secret for bob: 4242"


def test_resource_request_builder_carries_the_retry_fields():
    request = rs._build_read_resource_request("vault://bob", {"traceparent": "t"}, {"pin": _answer(pin="p")}, "sealed")
    wire = request.model_dump(by_alias=True, exclude_none=True)["params"]
    assert wire["requestState"] == "sealed"
    assert wire["inputResponses"]["pin"]["content"] == {"pin": "p"}
    assert wire["_meta"] == {"traceparent": "t"}


# --------------------------------------------------------------------------- #
# TRANSPORT: era gate, relay and retry threading on both handlers
# --------------------------------------------------------------------------- #


@pytest.fixture
def fake_db(monkeypatch):
    @asynccontextmanager
    async def fake_get_db():
        yield MagicMock()

    monkeypatch.setattr("mcpgateway.transports.streamablehttp_transport.get_db", fake_get_db)


def _request_context(version: str, params: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.meta = None
    ctx.protocol_version = version
    ctx.params = params or {}
    return ctx


@pytest.mark.asyncio
async def test_prompt_handler_relays_the_question_to_a_modern_caller(fake_db, monkeypatch):
    question = _question("name", "Your name?", "sealed")
    monkeypatch.setattr(tr.prompt_service, "get_prompt", AsyncMock(side_effect=PromptInputRequired(question)))
    with patch.object(type(tr.mcp_app), "request_context", new_callable=PropertyMock, return_value=_request_context(MODERN)):
        assert await tr.get_prompt("up-needs-input", {}) is question


@pytest.mark.asyncio
async def test_prompt_handler_refuses_a_legacy_caller_cleanly(fake_db, monkeypatch):
    monkeypatch.setattr(tr.prompt_service, "get_prompt", AsyncMock(side_effect=PromptInputRequired(_question("name", "Your name?", "sealed"))))
    with patch.object(type(tr.mcp_app), "request_context", new_callable=PropertyMock, return_value=_request_context(LEGACY)):
        with pytest.raises(MCPError) as exc_info:
            await tr.get_prompt("up-needs-input", {})
    assert exc_info.value.error.code == types.INTERNAL_ERROR
    assert exc_info.value.error.message == "Elicitation not supported"


@pytest.mark.asyncio
async def test_prompt_handler_threads_the_retry_to_the_service(fake_db, monkeypatch):
    captured = {}

    async def fake_get_prompt(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(messages=[], description=None)

    monkeypatch.setattr(tr.prompt_service, "get_prompt", AsyncMock(side_effect=fake_get_prompt))
    params = {"name": "up-needs-input", "inputResponses": {"name": {"action": "accept", "content": {"name": "madhu"}}}, "requestState": "sealed"}
    with patch.object(type(tr.mcp_app), "request_context", new_callable=PropertyMock, return_value=_request_context(MODERN, params)):
        await tr.get_prompt("up-needs-input", {})
    assert captured["request_state"] == "sealed"
    assert captured["input_responses"]["name"].content == {"name": "madhu"}


@pytest.mark.asyncio
async def test_resource_handler_relays_the_question_to_a_modern_caller(fake_db, monkeypatch):
    question = _question("pin", "Pin?", "sealed")
    monkeypatch.setattr(tr.resource_service, "read_resource", AsyncMock(side_effect=ResourceInputRequired(question)))
    with patch.object(type(tr.mcp_app), "request_context", new_callable=PropertyMock, return_value=_request_context(MODERN)):
        assert await tr.read_resource("vault://bob") is question


@pytest.mark.asyncio
async def test_resource_handler_refuses_a_legacy_caller_cleanly(fake_db, monkeypatch):
    monkeypatch.setattr(tr.resource_service, "read_resource", AsyncMock(side_effect=ResourceInputRequired(_question("pin", "Pin?", "sealed"))))
    with patch.object(type(tr.mcp_app), "request_context", new_callable=PropertyMock, return_value=_request_context(LEGACY)):
        with pytest.raises(MCPError) as exc_info:
            await tr.read_resource("vault://bob")
    assert exc_info.value.error.code == types.INTERNAL_ERROR
    assert exc_info.value.error.message == "Elicitation not supported"


@pytest.mark.asyncio
async def test_resource_handler_threads_the_retry_to_the_service(fake_db, monkeypatch):
    captured = {}

    async def fake_read_resource(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(text="secret", blob=None)

    monkeypatch.setattr(tr.resource_service, "read_resource", AsyncMock(side_effect=fake_read_resource))
    params = {"uri": "vault://bob", "inputResponses": {"pin": {"action": "accept", "content": {"pin": "4242"}}}, "requestState": "sealed"}
    with patch.object(type(tr.mcp_app), "request_context", new_callable=PropertyMock, return_value=_request_context(MODERN, params)):
        await tr.read_resource("vault://bob")
    assert captured["request_state"] == "sealed"
    assert captured["input_responses"]["pin"].content == {"pin": "4242"}


@pytest.mark.asyncio
async def test_read_resource_adapter_passes_the_question_through(monkeypatch):
    question = _question("pin", "Pin?", "sealed")
    monkeypatch.setattr(tr, "read_resource", AsyncMock(return_value=question))
    result = await tr._adapt_read_resource(MagicMock(), SimpleNamespace(uri="vault://bob"))
    assert result is question


@pytest.mark.asyncio
async def test_direct_proxy_read_raises_the_signal_and_forwards_the_retry(monkeypatch, upstream):
    """The direct proxy goes through the real in-process upstream: question first, content after the answer."""

    @asynccontextmanager
    async def fake_proxy_client(**_kwargs):
        async with Client(upstream, mode=MODERN) as client:
            yield client

    monkeypatch.setattr(tr, "mcp_proxy_client", fake_proxy_client)
    monkeypatch.setattr(tr, "build_gateway_auth_headers", lambda _gateway: {})
    monkeypatch.setattr(tr, "get_passthrough_headers", lambda *_args, **_kwargs: {}, raising=False)
    gateway = SimpleNamespace(id="gw-1", url="http://upstream.test/mcp", auth_type=None, auth_value=None)

    with pytest.raises(ResourceInputRequired) as signal:
        await tr._proxy_read_resource_to_gateway(gateway, "vault://bob", {}, None)
    assert set(signal.value.result.input_requests) == {"pin"}

    contents = await tr._proxy_read_resource_to_gateway(gateway, "vault://bob", {}, None, {"pin": _answer(pin="4242")}, signal.value.result.request_state)
    assert contents[0].text == "secret for bob: 4242"
