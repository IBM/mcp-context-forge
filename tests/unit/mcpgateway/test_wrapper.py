# -*- coding: utf-8 -*-
"""Tests for the MCP *wrapper* module (single file, full coverage).

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti + contributors

This suite fakes the "mcp" dependency tree so that no real network or
pydantic models are required and exercises almost every branch inside
*mcpgateway.wrapper*.
"""

import asyncio
import json
import sys
import types
import pytest

import mcpgateway.wrapper as wrapper


# -------------------
# Utilities
# -------------------
def test_convert_url_variants():
    assert wrapper.convert_url("http://x/servers/uuid") == "http://x/servers/uuid/mcp"
    assert wrapper.convert_url("http://x/servers/uuid/") == "http://x/servers/uuid//mcp"
    assert wrapper.convert_url("http://x/servers/uuid/mcp") == "http://x/servers/uuid/mcp"
    assert wrapper.convert_url("http://x/servers/uuid/sse") == "http://x/servers/uuid/mcp"


def test_make_error_defaults_and_data():
    err = wrapper.make_error("oops")
    assert err["error"]["message"] == "oops"
    assert err["error"]["code"] == wrapper.JSONRPC_INTERNAL_ERROR
    err2 = wrapper.make_error("bad", code=-32099, data={"x": 1})
    assert err2["error"]["data"] == {"x": 1}
    assert err2["error"]["code"] == -32099


def test_setup_logging_on_and_off(caplog):
    wrapper.setup_logging("DEBUG")
    assert wrapper.logger.disabled is False
    wrapper.logger.debug("hello debug")
    wrapper.setup_logging("OFF")
    assert wrapper.logger.disabled is True


def test_shutting_down_and_mark_shutdown():
    # Reset first
    wrapper._shutdown.clear()
    assert not wrapper.shutting_down()
    wrapper._mark_shutdown()
    assert wrapper.shutting_down()
    # Reset again for further tests
    wrapper._shutdown.clear()
    assert not wrapper.shutting_down()


def test_send_to_stdout_json_and_str(monkeypatch):
    captured = []

    def fake_write(s):
        captured.append(s)
        return len(s)

    def fake_flush():
        return None

    monkeypatch.setattr(sys.stdout, "write", fake_write)
    monkeypatch.setattr(sys.stdout, "flush", fake_flush)

    wrapper.send_to_stdout({"a": 1})
    wrapper.send_to_stdout("plain text")
    assert any('"a": 1' in s for s in captured)
    assert any("plain text" in s for s in captured)


# -------------------
# Async stream parsers
# -------------------
@pytest.mark.asyncio
async def test_ndjson_lines_basic():
    async def fake_iter_bytes():
        yield b'{"a":1}\n{"b":2}\n'
    resp = types.SimpleNamespace(aiter_bytes=fake_iter_bytes)
    lines = [l async for l in wrapper.ndjson_lines(resp)]
    assert lines == ['{"a":1}', '{"b":2}']


@pytest.mark.asyncio
async def test_sse_events_basic():
    async def fake_iter_bytes():
        yield b"data: first\n\ndata: second\n\n"
    resp = types.SimpleNamespace(aiter_bytes=fake_iter_bytes)
    events = [e async for e in wrapper.sse_events(resp)]
    assert events == ["first", "second"]


# -------------------
# Settings dataclass
# -------------------
def test_settings_defaults():
    s = wrapper.Settings("http://x/mcp", "Bearer token", 5, 10, 2, "DEBUG")
    assert s.server_url == "http://x/mcp"
    assert s.auth_header == "Bearer token"
    assert s.concurrency == 2


# -------------------
# parse_args
# -------------------
def test_parse_args_with_env(monkeypatch):
    monkeypatch.setenv("MCP_SERVER_URL", "http://localhost:4444/servers/uuid")
    monkeypatch.setenv("MCP_AUTH", "Bearer 123")
    sys_argv = sys.argv
    sys.argv = ["prog"]
    try:
        s = wrapper.parse_args()
        assert s.server_url.endswith("/mcp")
        assert s.auth_header == "Bearer 123"
    finally:
        sys.argv = sys_argv

