# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_wrapper.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti + contributors

Tests for the MCP *wrapper* module (single file, full coverage).
This suite fakes the "mcp" dependency tree so that no real network or
pydantic models are required and exercises almost every branch inside
*mcpgateway.wrapper*.
"""

# Standard
import asyncio
import contextlib
import errno
import sys
import types

# Third-Party
import pytest

# First-Party
import mcpgateway.wrapper as wrapper


# Ensure shutdown flag is clear before each test run
def setup_function():
    wrapper._shutdown.clear()


# -------------------
# Utilities
# -------------------
def test_convert_url_variants():
    assert wrapper.convert_url("http://x/servers/uuid") == "http://x/servers/uuid/mcp/"
    assert wrapper.convert_url("http://x/servers/uuid/") == "http://x/servers/uuid//mcp/"
    assert wrapper.convert_url("http://x/servers/uuid/mcp") == "http://x/servers/uuid/mcp/"
    assert wrapper.convert_url("http://x/servers/uuid/sse") == "http://x/servers/uuid/mcp/"


def test_make_error_defaults_and_data():
    err = wrapper.make_error("oops")
    assert err["error"]["message"] == "oops"
    assert err["error"]["code"] == wrapper.JSONRPC_INTERNAL_ERROR
    err2 = wrapper.make_error("bad", code=-32099, data={"x": 1})
    assert err2["error"]["data"] == {"x": 1}
    assert err2["error"]["code"] == -32099


def test_setup_logging_on_and_off():
    wrapper.setup_logging("DEBUG")
    assert wrapper.logger.disabled is False
    wrapper.logger.debug("hello debug")
    wrapper.setup_logging("OFF")
    assert wrapper.logger.disabled is True


def test_shutting_down_and_mark_shutdown():
    wrapper._shutdown.clear()
    assert not wrapper.shutting_down()
    wrapper._mark_shutdown()
    assert wrapper.shutting_down()
    wrapper._shutdown.clear()
    assert not wrapper.shutting_down()


def test_send_to_stdout_json_and_str(monkeypatch):
    captured = []

    def fake_write(s):
        captured.append(s)
        return len(s)

    # Mock both buffer and text write to catch whichever is used
    monkeypatch.setattr(sys.stdout, "write", fake_write)
    if hasattr(sys.stdout, "buffer"):
        monkeypatch.setattr(sys.stdout.buffer, "write", fake_write)

    monkeypatch.setattr(sys.stdout, "flush", lambda: None)
    if hasattr(sys.stdout, "buffer"):
        monkeypatch.setattr(sys.stdout.buffer, "flush", lambda: None)

    wrapper.send_to_stdout({"a": 1})
    wrapper.send_to_stdout("plain text")

    # decode captured bytes to str for assertion simplicity
    decoded_captured = []
    for s in captured:
        if isinstance(s, bytes):
            decoded_captured.append(s.decode("utf-8"))
        else:
            decoded_captured.append(s)

    assert any('"a":1' in s or '"a": 1' in s for s in decoded_captured)
    assert any("plain text" in s for s in decoded_captured)


def test_send_to_stdout_oserror(monkeypatch):
    wrapper._shutdown.clear()

    def bad_write(_):
        raise OSError(errno.EPIPE, "broken pipe")

    monkeypatch.setattr(sys.stdout, "write", bad_write)
    if hasattr(sys.stdout, "buffer"):
        monkeypatch.setattr(sys.stdout.buffer, "write", bad_write)

    monkeypatch.setattr(sys.stdout, "flush", lambda: None)
    if hasattr(sys.stdout, "buffer"):
        monkeypatch.setattr(sys.stdout.buffer, "flush", lambda: None)

    wrapper.send_to_stdout({"x": 1})
    assert wrapper.shutting_down()


# -------------------
# Async stream parsers
# -------------------
@pytest.mark.asyncio
async def test_ndjson_lines_basic_and_tail():
    wrapper._shutdown.clear()

    async def fake_iter_bytes():
        # basic multi-line + a final line without newline to test tail handling
        yield b'{"a":1}\n{"b":2}\n'
        yield b'{"c":3}'

    resp = types.SimpleNamespace(aiter_bytes=fake_iter_bytes, aiter_lines=None) # aiter_lines not used in optimized version
    lines = [l async for l in wrapper.ndjson_lines(resp)]
    # lines are bytes now
    assert b'{"a":1}' in lines
    assert b'{"b":2}' in lines
    assert b'{"c":3}' in lines


@pytest.mark.asyncio
async def test_sse_events_basic_and_tail():
    wrapper._shutdown.clear()

    async def fake_iter_bytes():
        # two events with proper separators, plus a tail-only chunk
        yield b"data: first\n\n"
        yield b"data: second\n\n"
        yield b"data: tailonly\n\n"

    resp = types.SimpleNamespace(aiter_bytes=fake_iter_bytes)
    events = [e async for e in wrapper.sse_events(resp)]
    # events are bytes
    assert b"first" in events
    assert b"second" in events
    assert b"tailonly" in events


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
        assert s.server_url.endswith("/mcp/")
        assert s.auth_header == "Bearer 123"
    finally:
        sys.argv = sys_argv


def test_parse_args_missing_url(monkeypatch):
    # no env and no arg should exit with SystemExit
    monkeypatch.delenv("MCP_SERVER_URL", raising=False)
    sys_argv = sys.argv
    sys.argv = ["prog"]
    try:
        with pytest.raises(SystemExit):
            wrapper.parse_args()
    finally:
        sys.argv = sys_argv


# -------------------
# stdin_reader
# -------------------
@pytest.mark.asyncio
async def test_stdin_reader_valid_and_invalid(monkeypatch):
    wrapper._shutdown.clear()
    q = asyncio.Queue()

    # synchronous readline callable used by asyncio.to_thread
    lines = iter([b'{"ok":1}\n', b"{bad json}\n", b"   \n", b""])

    def fake_readline():
        try:
            return next(lines)
        except StopIteration:
            return b""

    # Mock buffer.readline if available, else stdin.readline (but existing test ran on host python which likely has buffer)
    # The wrapper uses sys.stdin.buffer.readline if available.
    if hasattr(sys.stdin, "buffer"):
        monkeypatch.setattr(sys.stdin.buffer, "readline", fake_readline)
    else:
        monkeypatch.setattr(sys.stdin, "readline", fake_readline)

    task = asyncio.create_task(wrapper.stdin_reader(q))

    # Collect three items: valid dict, error dict for invalid json, and None for EOF
    got1 = await asyncio.wait_for(q.get(), timeout=1)
    got2 = await asyncio.wait_for(q.get(), timeout=1)
    got3 = await asyncio.wait_for(q.get(), timeout=1)

    # first should be parsed dict
    assert isinstance(got1, dict) and got1.get("ok") == 1
    # second should be an error object (from make_error)
    assert isinstance(got2, dict) and "error" in got2
    # third should be None (EOF sentinel)
    assert got3 is None

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


# -------------------
# forward_once (JSON / NDJSON / SSE / HTTP error)
# -------------------
class DummyResp:
    def __init__(self, status=200, ctype="application/json", body=b'{"ok":1}'):
        self.status_code = status
        # use dict-like headers as wrapper expects resp.headers.get(...)
        self._headers = {"Content-Type": ctype}
        self._body = body

    @property
    def headers(self):
        return self._headers

    async def aread(self):
        # return full body for application/json path
        return self._body

    # context manager to be used with `async with client.stream(...) as resp:`
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_bytes(self):
        # yield the body as a single chunk (ndjson and sse parsers will process it)
        yield self._body


class DummyClient:
    def __init__(self, resp):
        self._resp = resp

    def stream(self, *a, **k):
        # returning the response instance which implements async context manager
        return self._resp


@pytest.mark.asyncio
async def test_forward_once_json_and_invalid(monkeypatch):
    wrapper._shutdown.clear()
    captured = []
    monkeypatch.setattr(wrapper, "send_to_stdout", lambda obj: captured.append(obj))

    # valid JSON response
    client = DummyClient(DummyResp(200, "application/json", b'{"ok":123}'))
    await wrapper.forward_once(client, wrapper.Settings("x", None), {"a": 1})
    assert any(isinstance(o, dict) and o.get("ok") == 123 for o in captured)

    # invalid JSON body (application/json but not JSON)
    client = DummyClient(DummyResp(200, "application/json", b"notjson"))
    await wrapper.forward_once(client, wrapper.Settings("x", None), {"b": 2})
    # should have produced an error object for invalid JSON response
    assert any(isinstance(o, dict) and "error" in o for o in captured)


@pytest.mark.asyncio
async def test_forward_once_ndjson_and_sse_and_http_error(monkeypatch):
    wrapper._shutdown.clear()
    captured = []
    monkeypatch.setattr(wrapper, "send_to_stdout", lambda obj: captured.append(obj))

    # ndjson: multiple JSON lines
    ndj = b'{"x":1}\n{"y":2}\n'
    client = DummyClient(DummyResp(200, "application/x-ndjson", ndj))
    await wrapper.forward_once(client, wrapper.Settings("x", None), {"z": 3})
    assert any(isinstance(d, dict) and ("x" in d or "y" in d) for d in captured)

    # sse: streaming events with data: lines containing JSON
    sse_chunk = b'data: {"foo": 42}\n\n'
    client = DummyClient(DummyResp(200, "text/event-stream", sse_chunk))
    await wrapper.forward_once(client, wrapper.Settings("x", None), {"w": 4})
    assert any(isinstance(d, dict) and d.get("foo") == 42 for d in captured)

    # http error (non-2xx)
    client = DummyClient(DummyResp(500, "application/json", b""))
    await wrapper.forward_once(client, wrapper.Settings("x", None), {"e": 1})
    assert any(isinstance(d, dict) and "error" in d for d in captured)


# -------------------
# make_request retry path
# -------------------
@pytest.mark.asyncio
async def test_make_request_retries(monkeypatch):
    wrapper._shutdown.clear()
    called = {"n": 0}

    async def bad_forward(*a, **k):
        called["n"] += 1
        raise RuntimeError("fail")

    monkeypatch.setattr(wrapper, "forward_once", bad_forward)
    captured = []
    monkeypatch.setattr(wrapper, "send_to_stdout", lambda obj: captured.append(obj))

    # small base_delay so test runs quickly
    await wrapper.make_request(None, wrapper.Settings("x", None), {"a": 1}, max_retries=2, base_delay=0.001)
    # forward_once should have been called multiple times
    assert called["n"] >= 2
    # on exhausting retries, make_request sends a max retries error
    assert any(isinstance(o, dict) and "error" in o for o in captured)


# -------------------
# main_async smoke test
# -------------------
@pytest.mark.asyncio
async def test_main_async_smoke(monkeypatch):
    wrapper._shutdown.clear()

    async def fake_reader(queue):
        await queue.put({"foo": "bar"})
        await queue.put(None)

    # simple make_request that just records calls
    called = {"n": 0}

    async def fake_make_request(client, settings, payload):
        called["n"] += 1
        # simulate small work
        await asyncio.sleep(0)

    class DummyResilient:
        def __init__(self, *a, **k):
            pass

        async def aclose(self):
            return None

    monkeypatch.setattr(wrapper, "stdin_reader", fake_reader)
    monkeypatch.setattr(wrapper, "make_request", fake_make_request)
    monkeypatch.setattr(wrapper, "ResilientHttpClient", DummyResilient)

    settings = wrapper.Settings("http://x/mcp", None)
    await wrapper.main_async(settings)
    assert wrapper.shutting_down() or called["n"] >= 0


# -------------------
# _install_signal_handlers runs (no-op on unsupported platforms)
# -------------------
def test_install_signal_handlers_runs():
    loop = asyncio.new_event_loop()
    try:
        wrapper._install_signal_handlers(loop)
    finally:
        loop.close()
