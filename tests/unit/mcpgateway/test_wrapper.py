# -*- coding: utf-8 -*-
"""Tests for the MCP *wrapper* module (single file, full coverage).

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti + contributors

This suite fakes the "mcp" dependency tree so that no real network or
pydantic models are required and exercises almost every branch inside
*mcpgateway.wrapper*.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import importlib
import sys
from types import ModuleType
from typing import Any, Dict, List

# Third-Party
import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Fake "mcp" package hierarchy
# ─────────────────────────────────────────────────────────────────────────────


def _install_fake_mcp(monkeypatch) -> None:
    """Install a dummy *mcp* package into *sys.modules* (idempotent)."""
    # wipe any existing real package
    for name in list(sys.modules):
        if name == "mcp" or name.startswith("mcp."):
            sys.modules.pop(name)

    if "mcp" in sys.modules:  # already stubbed
        return

    mcp = ModuleType("mcp")
    server_mod = ModuleType("mcp.server")
    stdio_mod = ModuleType("mcp.server.stdio")
    models_mod = ModuleType("mcp.server.models")
    types_mod = ModuleType("mcp.types")

    # ––– minimalist Server façade –––––––––––––––––––––––––––––––––––––––– #
    class _FakeServer:
        was_run: bool = False  # class-level flag

        def __init__(self, name: str):
            self.name = name

        # decorator helpers just hand the coroutine straight back
        def list_tools(self):
            return lambda fn: fn

        def call_tool(self):
            return lambda fn: fn

        def list_resources(self):
            return lambda fn: fn

        def read_resource(self):
            return lambda fn: fn

        def list_prompts(self):
            return lambda fn: fn

        def get_prompt(self):
            return lambda fn: fn

        def get_capabilities(self, **_):  # used by wrapper
            return {}

        async def run(self, *_a, **_kw):  # invoked by main()
            _FakeServer.was_run = True

    server_mod.Server = _FakeServer
    server_mod.NotificationOptions = type("NotificationOptions", (), {})
    server_mod.stdio = stdio_mod
    server_mod.models = models_mod
    mcp.server = server_mod  # type: ignore[attr-defined]

    # ––– stdio helper used by wrapper.main() –––––––––––––––––––––––––––––– #
    class _DummyStdIOServer:
        async def __aenter__(self):
            return "reader", "writer"

        async def __aexit__(self, *_):
            return False

    stdio_mod.stdio_server = lambda: _DummyStdIOServer()  # type: ignore[attr-defined]

    # ––– pydantic placeholder that *accepts* any kwargs ––––––––––––––––––– #
    class _InitOpts:
        def __init__(self, *_, **__):  # swallow anything
            pass

    models_mod.InitializationOptions = _InitOpts

    # ––– ultra-thin DTOs referenced by wrapper's handlers –––––––––––––––– #
    class _Tool:
        def __init__(self, name: str, description: str, inputSchema: dict, annotations: dict = None):
            self.name, self.description, self.inputSchema = name, description, inputSchema
            self.annotations = annotations or {}

    class _Resource:
        def __init__(self, uri: str, name: str, description: str, mimeType: str):
            self.uri, self.name, self.description, self.mimeType = uri, name, description, mimeType

    class _Prompt:
        def __init__(self, name: str, description: str, arguments: list):
            self.name, self.description, self.arguments = name, description, arguments

    class _TextContent:
        def __init__(self, type: str, text: str):
            self.type, self.text = type, text

    class _PromptMessage:
        def __init__(self, role: str, content: Any):
            self.role, self.content = role, content

    class _GetPromptResult:
        def __init__(self, description: str, messages: list):
            self.description, self.messages = description, messages

    types_mod.Tool = _Tool
    types_mod.Resource = _Resource
    types_mod.Prompt = _Prompt
    types_mod.TextContent = _TextContent
    types_mod.ImageContent = object
    types_mod.EmbeddedResource = object
    types_mod.PromptMessage = _PromptMessage
    types_mod.GetPromptResult = _GetPromptResult
    mcp.types = types_mod  # type: ignore[attr-defined]

    # register the whole fake tree
    sys.modules.update(
        {
            "mcp": mcp,
            "mcp.server": server_mod,
            "mcp.server.stdio": stdio_mod,
            "mcp.server.models": models_mod,
            "mcp.types": types_mod,
        }
    )
    monkeypatch.syspath_prepend(".")


# ─────────────────────────────────────────────────────────────────────────────
# Pytest plumbing
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture()
def wrapper(monkeypatch):
    """(Re)imports *mcpgateway.wrapper* with the fake MCP stack in place."""
    _install_fake_mcp(monkeypatch)
    monkeypatch.setenv("MCP_SERVER_CATALOG_URLS", "https://host.com/servers/1")
    sys.modules.pop("mcpgateway.wrapper", None)  # ensure fresh import
    return importlib.import_module("mcpgateway.wrapper")


# ─────────────────────────────────────────────────────────────────────────────
# Tiny *httpx* doubles
# ─────────────────────────────────────────────────────────────────────────────


class _Resp:
    """Bare-bones httpx.Response-like test double."""

    def __init__(self, *, json_data=None, text="OK", status: int = 200):
        self._json = json_data
        self.text = text
        self.status_code = status

    # minimal surface used by wrapper
    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            # Third-Party
            import httpx

            req = httpx.Request("GET", "x")
            raise httpx.HTTPStatusError("err", request=req, response=httpx.Response(self.status_code, request=req))


# ─────────────────────────────────────────────────────────────────────────────
# Helper for POST-based tool-call tests
# ─────────────────────────────────────────────────────────────────────────────


def _patch_client(monkeypatch, wrapper, *, json=None, exc=None):
    class _Client:
        def __init__(self, *_, **__):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, *_a, **_k):
            if exc:
                raise exc
            return _Resp(json_data=json)

    monkeypatch.setattr(wrapper.httpx, "AsyncClient", _Client)


# ─────────────────────────────────────────────────────────────────────────────
# Extra helper for fetch-json stubs used by metadata tests
# ─────────────────────────────────────────────────────────────────────────────


def _json_fetcher(payload: Any):
    async def _fake(_url: str):
        return _Resp(json_data=payload)

    return _fake


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests
# ─────────────────────────────────────────────────────────────────────────────

# ––– _extract_base_url happy-path parametrised –––––––––––––––––––––––––––– #


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://x.com/s/1", "https://x.com/s/1"),  # path preserved
        ("https://x.com/gw/servers/99", "https://x.com/gw"),
        ("https://x.com/gw/servers", "https://x.com/gw"),
        ("https://x.com/gw", "https://x.com/gw"),
    ],
)
def test_extract_base_url(raw, expected, wrapper):
    assert wrapper._extract_base_url(raw) == expected


# ––– _extract_base_url error branch –––––––––––––––––––––––––––––––––––––––– #


def test_extract_base_url_invalid(wrapper):
    with pytest.raises(ValueError):
        wrapper._extract_base_url("just-text-no-scheme")


# ––– fetch_url success / error paths ––––––––––––––––––––––––––––––––––––––– #


@pytest.mark.asyncio
async def test_fetch_url_ok(monkeypatch, wrapper):
    class _Client:
        def __init__(self, *_, **__):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url, **_):
            _Client.url = url
            return _Resp(json_data={"ok": 1})

    monkeypatch.setattr(wrapper.httpx, "AsyncClient", _Client)
    r = await wrapper.fetch_url("u")
    assert r.json() == {"ok": 1} and _Client.url == "u"


@pytest.mark.asyncio
async def test_fetch_url_request_error(monkeypatch, wrapper):
    # Third-Party
    import httpx

    class _Client:
        def __init__(self, *_, **__):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, *_a, **_k):
            raise httpx.RequestError("net", request=httpx.Request("GET", "u"))

    monkeypatch.setattr(wrapper.httpx, "AsyncClient", _Client)
    with pytest.raises(httpx.RequestError):
        await wrapper.fetch_url("u")


@pytest.mark.asyncio
async def test_fetch_url_http_status(monkeypatch, wrapper):
    class _Client:
        def __init__(self, *_, **__):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, *_a, **_k):
            return _Resp(status=500)

    monkeypatch.setattr(wrapper.httpx, "AsyncClient", _Client)
    # Third-Party
    import httpx

    with pytest.raises(httpx.HTTPStatusError):
        await wrapper.fetch_url("u")


# ––– handle_call_tool –––––––––––––––––––––––––––––––––––––––––––––––––––––– #


@pytest.mark.asyncio
async def test_handle_call_tool_ok(monkeypatch, wrapper):
    _patch_client(monkeypatch, wrapper, json={"result": "pong"})
    out = await wrapper.handle_call_tool("ping", {})
    assert out[0].text == "pong"


@pytest.mark.asyncio
async def test_handle_call_tool_error(monkeypatch, wrapper):
    _patch_client(monkeypatch, wrapper, json={"error": {"message": "bad"}})
    with pytest.raises(RuntimeError, match=r"Tool call failed: bad"):
        await wrapper.handle_call_tool("x", {})


@pytest.mark.asyncio
async def test_handle_call_tool_timeout(monkeypatch, wrapper):
    # Third-Party
    import httpx

    _patch_client(monkeypatch, wrapper, exc=httpx.TimeoutException("t"))
    with pytest.raises(RuntimeError, match=r"timeout"):
        await wrapper.handle_call_tool("x", {})


# ––– handle_read_resource –––––––––––––––––––––––––––––––––––––––––––––––––– #


@pytest.mark.asyncio
async def test_read_resource(monkeypatch, wrapper):
    async def _fake(u):
        return _Resp(text="body")

    monkeypatch.setattr(wrapper, "fetch_url", _fake)
    assert await wrapper.handle_read_resource("u") == "body"


# ––– handle_get_prompt –––––––––––––––––––––––––––––––––––––––––––––––––––– #


@pytest.mark.asyncio
async def test_get_prompt(monkeypatch, wrapper):
    async def _fake(_):
        return _Resp(json_data={"template": "Hi {n}", "description": ""})

    monkeypatch.setattr(wrapper, "fetch_url", _fake)
    res = await wrapper.handle_get_prompt("greet", {"n": "Bob"})
    assert res.messages[0].content.text == "Hi Bob"


@pytest.mark.asyncio
async def test_get_prompt_missing(monkeypatch, wrapper):
    async def _fake(_):
        return _Resp(json_data={"template": "Hi {n}"})

    monkeypatch.setattr(wrapper, "fetch_url", _fake)
    with pytest.raises(ValueError, match="Missing placeholder"):
        await wrapper.handle_get_prompt("greet", {})


# ––– handle_list_tools branch –––––––––––––––––––––––––––––––––––––––––––––– #


@pytest.mark.asyncio
async def test_handle_list_tools(monkeypatch, wrapper):
    async def _ids(_):  # noqa: D401
        return ["1"]

    async def _meta(_):
        return [{"name": "A", "description": "", "inputSchema": {}}]

    monkeypatch.setattr(wrapper, "get_tools_from_mcp_server", _ids)
    monkeypatch.setattr(wrapper, "tools_metadata", _meta)
    tools = await wrapper.handle_list_tools()
    assert tools and tools[0].name == "A"


# ––– get_tools_from_mcp_server & tools_metadata branches ––––––––––––––––––– #


@pytest.mark.asyncio
async def test_get_tools_and_metadata(monkeypatch, wrapper):
    # fake catalog → two servers with associated tools
    catalog = [
        {"id": "1", "associatedTools": ["10", "11"]},
        {"id": "2", "associatedTools": ["20"]},
    ]
    monkeypatch.setattr(wrapper, "fetch_url", _json_fetcher(catalog))
    out = await wrapper.get_tools_from_mcp_server(["https://host.com/servers/1"])
    assert out == ["10", "11"]

    # now cover tools_metadata *filter* & *all* paths
    tools_payload = [
        {"id": "10", "name": "A"},
        {"id": "11", "name": "B"},
    ]
    monkeypatch.setattr(wrapper, "fetch_url", _json_fetcher(tools_payload))
    subset = await wrapper.tools_metadata(["10"])
    assert subset == [{"id": "10", "name": "A"}]

    everything = await wrapper.tools_metadata(["0"])
    assert everything == tools_payload


# ––– get_resources_from_mcp_server & get_prompts_from_mcp_server ––––––––––– #


@pytest.mark.asyncio
async def test_get_resources_and_prompts(monkeypatch, wrapper):
    catalog = [
        {"id": "1", "associatedResources": ["r1"]},
        {"id": "2", "associatedPrompts": ["p1"]},
    ]
    monkeypatch.setattr(wrapper, "fetch_url", _json_fetcher(catalog))

    r_ids = await wrapper.get_resources_from_mcp_server(["https://host.com/servers/1"])
    assert r_ids == ["r1"]

    p_ids = await wrapper.get_prompts_from_mcp_server(["https://host.com/servers/2"])
    assert p_ids == ["p1"]


# ––– resources_metadata & prompts_metadata branches –––––––––––––––––––––––– #


@pytest.mark.asyncio
async def test_resources_and_prompts_metadata(monkeypatch, wrapper):
    resources_payload: List[Dict[str, Any]] = [
        {"id": "r1", "uri": "https://good.com/x", "name": "R"},
        {"id": "r2", "uri": "https://good.com/y", "name": "S"},
    ]
    monkeypatch.setattr(wrapper, "fetch_url", _json_fetcher(resources_payload))
    assert await wrapper.resources_metadata(["r1"]) == [resources_payload[0]]
    assert await wrapper.resources_metadata(["0"]) == resources_payload

    prompts_payload = [
        {"id": "p1", "name": "P", "description": "D", "arguments": []},
        {"id": "p2", "name": "Q", "description": "", "arguments": []},
    ]
    monkeypatch.setattr(wrapper, "fetch_url", _json_fetcher(prompts_payload))
    assert await wrapper.prompts_metadata(["p2"]) == [prompts_payload[1]]
    assert await wrapper.prompts_metadata(["0"]) == prompts_payload


# ––– handle_list_resources – skip invalid URI & keep good one –––––––––––––– #


@pytest.mark.asyncio
async def test_handle_list_resources(monkeypatch, wrapper):
    async def _ids(_catalog_urls):
        return ["xyz"]

    async def _meta(_ids):
        return [
            {"uri": "https://valid.com", "name": "OK", "description": "", "mimeType": "text/plain"},
            {"uri": "not-a-url", "name": "BAD", "description": "", "mimeType": "text/plain"},
        ]

    monkeypatch.setattr(wrapper, "get_resources_from_mcp_server", _ids)
    monkeypatch.setattr(wrapper, "resources_metadata", _meta)

    out = await wrapper.handle_list_resources()
    assert len(out) == 1 and str(out[0].uri).rstrip("/") == "https://valid.com"


# ––– handle_list_prompts happy path –––––––––––––––––––––––––––––––––––––––– #


@pytest.mark.asyncio
async def test_handle_list_prompts(monkeypatch, wrapper):
    async def _ids(_):
        return ["p1"]

    async def _meta(_):
        return [{"name": "Hello", "description": "", "arguments": []}]

    monkeypatch.setattr(wrapper, "get_prompts_from_mcp_server", _ids)
    monkeypatch.setattr(wrapper, "prompts_metadata", _meta)

    res = await wrapper.handle_list_prompts()
    assert res and res[0].name == "Hello"


# ––– wrapper.main wiring (ensures Server.run invoked) –––––––––––––––––––––– #


def test_main_runs_ok(wrapper):
    wrapper.server.__class__.was_run = False  # reset flag
    asyncio.run(wrapper.main())
    assert wrapper.server.__class__.was_run
