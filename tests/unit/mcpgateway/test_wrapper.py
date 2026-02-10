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
from unittest.mock import AsyncMock

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
    assert wrapper.convert_url("http://x/servers/uuid/mcp/") == "http://x/servers/uuid/mcp/"
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


def test_setup_logging_none_disables():
    wrapper.setup_logging("DEBUG")
    assert wrapper.logger.disabled is False
    wrapper.setup_logging(None)
    assert wrapper.logger.disabled is True


def test_shutting_down_and_mark_shutdown():
    wrapper._shutdown.clear()
    assert not wrapper.shutting_down()
    wrapper._mark_shutdown()
    assert wrapper.shutting_down()
    # Calling it again should hit the "already set" branch.
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


def test_send_to_stdout_oserror_other_errno(monkeypatch):
    wrapper._shutdown.clear()

    def bad_write(_):
        raise OSError(errno.EIO, "io error")

    monkeypatch.setattr(sys.stdout, "write", bad_write)
    if hasattr(sys.stdout, "buffer"):
        monkeypatch.setattr(sys.stdout.buffer, "write", bad_write)

    monkeypatch.setattr(sys.stdout, "flush", lambda: None)
    if hasattr(sys.stdout, "buffer"):
        monkeypatch.setattr(sys.stdout.buffer, "flush", lambda: None)

    wrapper.send_to_stdout({"x": 2})
    assert wrapper.shutting_down()


def test_send_to_stdout_no_buffer_fallback(monkeypatch):
    wrapper._shutdown.clear()
    captured = []

    class DummyStdout:
        def write(self, text):
            captured.append(text)
            return len(text)

        def flush(self):
            return None

    def raises(_):
        raise TypeError("boom")

    monkeypatch.setattr(wrapper, "orjson", types.SimpleNamespace(dumps=raises))
    monkeypatch.setattr(sys, "stdout", DummyStdout())

    wrapper.send_to_stdout("plain text")
    wrapper.send_to_stdout(b"bytes")

    assert any("plain text" in s for s in captured)
    assert any("bytes" in s for s in captured)


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
async def test_ndjson_lines_skips_empty_chunk_and_blank_lines():
    wrapper._shutdown.clear()

    async def fake_iter_bytes():
        yield b""
        yield b'{"a":1}\n\n{"b":2}\n'

    resp = types.SimpleNamespace(aiter_bytes=fake_iter_bytes)
    lines = [l async for l in wrapper.ndjson_lines(resp)]
    assert lines == [b'{"a":1}', b'{"b":2}']


@pytest.mark.asyncio
async def test_ndjson_lines_breaks_on_shutdown():
    wrapper._shutdown.clear()

    async def fake_iter_bytes():
        yield b'{"a":1}\n'
        wrapper._mark_shutdown()
        yield b'{"b":2}\n'

    resp = types.SimpleNamespace(aiter_bytes=fake_iter_bytes)
    lines = [l async for l in wrapper.ndjson_lines(resp)]
    assert lines == [b'{"a":1}']


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


@pytest.mark.asyncio
async def test_sse_events_handles_comments_blank_events_and_partial_line():
    wrapper._shutdown.clear()

    async def fake_iter_bytes():
        yield b""
        yield b": comment\n\n"
        yield b"data\n\n"
        yield b"data: tail"

    resp = types.SimpleNamespace(aiter_bytes=fake_iter_bytes)
    events = [e async for e in wrapper.sse_events(resp)]
    assert b"" in events  # from `data` line without value
    assert b"tail" in events


@pytest.mark.asyncio
async def test_sse_events_breaks_on_shutdown():
    wrapper._shutdown.clear()

    async def fake_iter_bytes():
        yield b"data: one\n\n"
        wrapper._mark_shutdown()
        yield b"data: two\n\n"

    resp = types.SimpleNamespace(aiter_bytes=fake_iter_bytes)
    events = [e async for e in wrapper.sse_events(resp)]
    assert events == [b"one"]


@pytest.mark.asyncio
async def test_sse_events_partial_line_without_colon():
    wrapper._shutdown.clear()

    async def fake_iter_bytes():
        # A normal event, then a trailing partial line with no ":" to hit the
        # `field, value = line, b""` branch in tail processing.
        yield b"event: message\ndata: one\n\n"
        yield b"data"

    resp = types.SimpleNamespace(aiter_bytes=fake_iter_bytes)
    events = [e async for e in wrapper.sse_events(resp)]
    assert b"one" in events
    assert b"" in events


@pytest.mark.asyncio
async def test_sse_events_tail_ignores_comment_and_non_data_fields():
    wrapper._shutdown.clear()

    async def fake_iter_bytes_comment_tail():
        yield b"data: one\n\n"
        yield b": this is a comment"

    resp1 = types.SimpleNamespace(aiter_bytes=fake_iter_bytes_comment_tail)
    events1 = [e async for e in wrapper.sse_events(resp1)]
    assert events1 == [b"one"]

    async def fake_iter_bytes_event_tail():
        yield b"data: one\n\n"
        yield b"event: message"

    resp2 = types.SimpleNamespace(aiter_bytes=fake_iter_bytes_event_tail)
    events2 = [e async for e in wrapper.sse_events(resp2)]
    assert events2 == [b"one"]


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


@pytest.mark.asyncio
async def test_stdin_reader_no_buffer_path(monkeypatch):
    wrapper._shutdown.clear()
    q = asyncio.Queue()

    lines = iter(["{bad json}\n", ""])

    class DummyStdin:
        def readline(self):
            return next(lines)

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(sys, "stdin", DummyStdin())
    monkeypatch.setattr(wrapper.asyncio, "to_thread", fake_to_thread)

    task = asyncio.create_task(wrapper.stdin_reader(q))
    got1 = await asyncio.wait_for(q.get(), timeout=1)
    got2 = await asyncio.wait_for(q.get(), timeout=1)

    assert isinstance(got1, dict) and "error" in got1
    assert got2 is None

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_stdin_reader_decode_failure_falls_back_to_str(monkeypatch):
    """Force line.decode() to raise so stdin_reader uses str(line) fallback."""
    wrapper._shutdown.clear()
    q: asyncio.Queue = asyncio.Queue()

    class FakeLine:
        def strip(self):
            return self

        def decode(self, *_a, **_k):
            raise UnicodeError("boom")

        def __len__(self):
            return 1

        def __str__(self):
            return "<FakeLine>"

    lines = iter([FakeLine(), b""])

    def fake_readline():
        return next(lines)

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    if hasattr(sys.stdin, "buffer"):
        monkeypatch.setattr(sys.stdin.buffer, "readline", fake_readline)
    else:
        monkeypatch.setattr(sys.stdin, "readline", fake_readline)

    monkeypatch.setattr(wrapper.asyncio, "to_thread", fake_to_thread)

    task = asyncio.create_task(wrapper.stdin_reader(q))
    err_obj = await asyncio.wait_for(q.get(), timeout=1)
    eof = await asyncio.wait_for(q.get(), timeout=1)

    assert isinstance(err_obj, dict) and err_obj.get("error", {}).get("data") == "<FakeLine>"
    assert eof is None

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


class CapturingClient:
    def __init__(self, resp):
        self._resp = resp
        self.calls = []

    def stream(self, *a, **k):
        self.calls.append(k)
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


@pytest.mark.asyncio
async def test_forward_once_form_encoding_and_auth_header(monkeypatch):
    wrapper._shutdown.clear()
    captured = []
    monkeypatch.setattr(wrapper, "send_to_stdout", lambda obj: captured.append(obj))

    client = CapturingClient(DummyResp(200, "application/json", b'{"ok":true}'))
    settings = wrapper.Settings("http://x/mcp", "Bearer token")
    settings.content_type = "application/x-www-form-urlencoded"

    await wrapper.forward_once(client, settings, {"a": "b", "c": 1})
    call = client.calls[0]
    assert call["headers"]["Authorization"] == "Bearer token"
    assert call["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert b"a=b" in call["data"]
    assert b"c=1" in call["data"]
    assert any(isinstance(o, dict) and o.get("ok") is True for o in captured)


@pytest.mark.asyncio
async def test_forward_once_returns_immediately_if_shutting_down(monkeypatch):
    wrapper._shutdown.clear()
    wrapper._mark_shutdown()

    class BoomClient:
        def stream(self, *a, **k):  # pragma: no cover - should not be called
            raise AssertionError("should not call stream")

    await wrapper.forward_once(BoomClient(), wrapper.Settings("http://x/mcp", None), {"a": 1})


@pytest.mark.asyncio
async def test_forward_once_form_encoding_non_dict_payload(monkeypatch):
    wrapper._shutdown.clear()
    monkeypatch.setattr(wrapper, "send_to_stdout", lambda _obj: None)

    client = CapturingClient(DummyResp(200, "application/json", b'{"ok":true}'))
    settings = wrapper.Settings("http://x/mcp", None)
    settings.content_type = "application/x-www-form-urlencoded"

    await wrapper.forward_once(client, settings, "a=b")
    call = client.calls[0]
    assert call["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert call["data"] == b"a=b"


@pytest.mark.asyncio
async def test_forward_once_auto_detect_urlencode_and_json(monkeypatch):
    wrapper._shutdown.clear()
    captured = []
    monkeypatch.setattr(wrapper, "send_to_stdout", lambda obj: captured.append(obj))

    client = CapturingClient(DummyResp(200, "application/json", b'{"ok":true}'))
    settings = wrapper.Settings("http://x/mcp", None)
    settings.content_type = "AUTO"

    await wrapper.forward_once(client, settings, {"a": "b", "c": 1})
    call1 = client.calls[-1]
    assert call1["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert b"a=b" in call1["data"]

    await wrapper.forward_once(client, settings, {"a": {"nested": 1}})
    call2 = client.calls[-1]
    assert call2["headers"]["Content-Type"].startswith("application/json")
    assert b'{"a":{"nested":1}}' in call2["data"]
    assert any(isinstance(o, dict) and o.get("ok") is True for o in captured)


@pytest.mark.asyncio
async def test_forward_once_returns_when_shutdown_triggered_inside_response(monkeypatch):
    wrapper._shutdown.clear()
    captured = []
    monkeypatch.setattr(wrapper, "send_to_stdout", lambda obj: captured.append(obj))

    class ShutdownResp(DummyResp):
        async def __aenter__(self):
            wrapper._mark_shutdown()
            return self

    client = DummyClient(ShutdownResp(200, "application/json", b'{"ok":1}'))
    await wrapper.forward_once(client, wrapper.Settings("x", None), {"a": 1})
    assert captured == []


@pytest.mark.asyncio
async def test_forward_once_application_json_skips_processing_if_shutdown_after_read(monkeypatch):
    wrapper._shutdown.clear()
    captured = []
    monkeypatch.setattr(wrapper, "send_to_stdout", lambda obj: captured.append(obj))

    class ShutdownAfterReadResp(DummyResp):
        async def aread(self):
            wrapper._mark_shutdown()
            return await super().aread()

    client = DummyClient(ShutdownAfterReadResp(200, "application/json", b'{"ok":1}'))
    await wrapper.forward_once(client, wrapper.Settings("x", None), {"a": 1})
    assert captured == []


@pytest.mark.asyncio
async def test_forward_once_process_line_returns_early_when_shutdown(monkeypatch):
    wrapper._shutdown.clear()
    captured = []
    monkeypatch.setattr(wrapper, "send_to_stdout", lambda obj: captured.append(obj))

    async def fake_ndjson_lines(_resp):
        yield b'{"x": 1}'

    monkeypatch.setattr(wrapper, "ndjson_lines", fake_ndjson_lines)

    calls = {"n": 0}

    def seq_shutting_down():
        calls["n"] += 1
        # 1: start check, 2: after response, 3: outer loop check, 4: inside _process_line
        return calls["n"] == 4

    monkeypatch.setattr(wrapper, "shutting_down", seq_shutting_down)

    client = DummyClient(DummyResp(200, "application/x-ndjson", b""))
    await wrapper.forward_once(client, wrapper.Settings("x", None), {"z": 3})
    assert captured == []


@pytest.mark.asyncio
async def test_forward_once_sse_empty_payload_continues_and_breaks_on_shutdown(monkeypatch):
    wrapper._shutdown.clear()
    captured = []

    def send_and_shutdown(obj):
        captured.append(obj)
        wrapper._mark_shutdown()

    monkeypatch.setattr(wrapper, "send_to_stdout", send_and_shutdown)

    body = b"data:\n\n" b'data: {"foo": 1}\n\n' b'data: {"bar": 2}\n\n'
    client = DummyClient(DummyResp(200, "text/event-stream", body))
    await wrapper.forward_once(client, wrapper.Settings("x", None), {"w": 4})
    assert any(isinstance(d, dict) and d.get("foo") == 1 for d in captured)
    assert not any(isinstance(d, dict) and d.get("bar") == 2 for d in captured)


@pytest.mark.asyncio
async def test_forward_once_ndjson_breaks_on_shutdown(monkeypatch):
    wrapper._shutdown.clear()
    captured = []

    def send_and_shutdown(obj):
        captured.append(obj)
        wrapper._mark_shutdown()

    monkeypatch.setattr(wrapper, "send_to_stdout", send_and_shutdown)

    ndj = b'{"x":1}\n{"y":2}\n'
    client = DummyClient(DummyResp(200, "application/x-ndjson", ndj))
    await wrapper.forward_once(client, wrapper.Settings("x", None), {"z": 3})
    assert any(isinstance(d, dict) and d.get("x") == 1 for d in captured)
    assert not any(isinstance(d, dict) and d.get("y") == 2 for d in captured)


@pytest.mark.asyncio
async def test_forward_once_fallback_parses_as_ndjson(monkeypatch):
    wrapper._shutdown.clear()
    captured = []
    monkeypatch.setattr(wrapper, "send_to_stdout", lambda obj: captured.append(obj))

    body = b'{"a":1}\n{"b":2}\n'
    client = DummyClient(DummyResp(200, "text/plain", body))
    await wrapper.forward_once(client, wrapper.Settings("x", None), {"z": 3})
    assert any(isinstance(d, dict) and d.get("a") == 1 for d in captured)
    assert any(isinstance(d, dict) and d.get("b") == 2 for d in captured)


@pytest.mark.asyncio
async def test_forward_once_fallback_breaks_on_shutdown(monkeypatch):
    wrapper._shutdown.clear()
    captured = []

    def send_and_shutdown(obj):
        captured.append(obj)
        wrapper._mark_shutdown()

    monkeypatch.setattr(wrapper, "send_to_stdout", send_and_shutdown)

    body = b'{"a":1}\n{"b":2}\n'
    client = DummyClient(DummyResp(200, "text/plain", body))
    await wrapper.forward_once(client, wrapper.Settings("x", None), {"z": 3})
    assert any(isinstance(d, dict) and d.get("a") == 1 for d in captured)
    assert not any(isinstance(d, dict) and d.get("b") == 2 for d in captured)


@pytest.mark.asyncio
async def test_forward_once_sse_invalid_json(monkeypatch):
    wrapper._shutdown.clear()
    captured = []
    monkeypatch.setattr(wrapper, "send_to_stdout", lambda obj: captured.append(obj))

    sse_chunk = b"data: notjson\n\n"
    client = DummyClient(DummyResp(200, "text/event-stream", sse_chunk))
    await wrapper.forward_once(client, wrapper.Settings("x", None), {"w": 4})
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


@pytest.mark.asyncio
async def test_make_request_success(monkeypatch):
    wrapper._shutdown.clear()

    called = {"n": 0}

    async def ok_forward(*_a, **_k):
        called["n"] += 1
        return None

    monkeypatch.setattr(wrapper, "forward_once", ok_forward)
    captured = []
    monkeypatch.setattr(wrapper, "send_to_stdout", lambda obj: captured.append(obj))

    await wrapper.make_request(None, wrapper.Settings("x", None), {"a": 1}, max_retries=2, base_delay=0.001)
    assert called["n"] == 1
    assert captured == []


@pytest.mark.asyncio
async def test_make_request_does_nothing_if_already_shutting_down(monkeypatch):
    wrapper._shutdown.clear()
    wrapper._mark_shutdown()

    async def boom(*_a, **_k):  # pragma: no cover - should not be called
        raise AssertionError("forward_once should not be called")

    monkeypatch.setattr(wrapper, "forward_once", boom)
    await wrapper.make_request(None, wrapper.Settings("x", None), {"a": 1}, max_retries=1, base_delay=0.001)


@pytest.mark.asyncio
async def test_make_request_returns_if_shutdown_triggered_in_exception(monkeypatch):
    wrapper._shutdown.clear()

    async def fail_and_shutdown(*_a, **_k):
        wrapper._mark_shutdown()
        raise RuntimeError("boom")

    monkeypatch.setattr(wrapper, "forward_once", fail_and_shutdown)
    captured = []
    monkeypatch.setattr(wrapper, "send_to_stdout", lambda obj: captured.append(obj))

    await wrapper.make_request(None, wrapper.Settings("x", None), {"a": 1}, max_retries=5, base_delay=0.001)
    # Should not emit "max retries exceeded" since shutdown was triggered.
    assert captured == []


# -------------------
# main_async smoke test
# -------------------
@pytest.mark.asyncio
async def test_main_async_smoke(monkeypatch):
    wrapper._shutdown.clear()

    worker_done = asyncio.Event()

    async def fake_reader(queue):
        await queue.put({"foo": "bar"})
        # Let the worker run before sending EOF
        await worker_done.wait()
        await queue.put(None)

    # simple make_request that just records calls
    called = {"n": 0}

    async def fake_make_request(client, settings, payload):
        called["n"] += 1
        worker_done.set()

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
    assert called["n"] >= 1, "make_request should have been called at least once"


@pytest.mark.asyncio
async def test_main_async_cancels_inflight_tasks(monkeypatch):
    wrapper._shutdown.clear()

    async def fake_reader(queue):
        await queue.put({"foo": "bar"})
        # Give main loop a chance to schedule the worker before EOF arrives.
        await asyncio.sleep(0)
        await queue.put(None)

    gate = asyncio.Event()

    async def blocking_make_request(*_a, **_k):
        await gate.wait()

    class DummyResilient:
        def __init__(self, *a, **k):
            self.closed = False

        async def aclose(self):
            self.closed = True

    monkeypatch.setattr(wrapper, "stdin_reader", fake_reader)
    monkeypatch.setattr(wrapper, "make_request", blocking_make_request)
    monkeypatch.setattr(wrapper, "ResilientHttpClient", DummyResilient)

    settings = wrapper.Settings("http://x/mcp", None, concurrency=1)
    await wrapper.main_async(settings)
    assert wrapper.shutting_down()


@pytest.mark.asyncio
async def test_main_async_ssl_verify_importerror_fallback(monkeypatch):
    wrapper._shutdown.clear()

    async def fake_reader(queue):
        await queue.put(None)

    created = {}

    class DummyResilient:
        def __init__(self, *a, **k):
            created["client_args"] = k.get("client_args")

        async def aclose(self):
            return None

    # Force mcpgateway.config import to fail inside main_async.
    import builtins

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
        if name == "mcpgateway.config":
            raise ImportError("no config")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    monkeypatch.setattr(wrapper, "stdin_reader", fake_reader)
    monkeypatch.setattr(wrapper, "ResilientHttpClient", DummyResilient)
    monkeypatch.setattr(wrapper, "make_request", AsyncMock())

    settings = wrapper.Settings("http://x/mcp", None)
    await wrapper.main_async(settings)
    assert created["client_args"]["verify"] is True


@pytest.mark.asyncio
async def test_main_async_exits_when_already_shutting_down(monkeypatch):
    """Cover the `while not shutting_down():` condition false branch."""
    wrapper._shutdown.clear()
    wrapper._mark_shutdown()

    async def fake_reader(_queue):
        return None

    def fake_create_task(coro):
        # main_async always cancels and awaits the reader task; return a done task
        # so cancellation is a no-op and no CancelledError leaks.
        coro.close()
        fut = asyncio.get_running_loop().create_future()
        fut.set_result(None)
        return fut

    class DummyResilient:
        def __init__(self, *a, **k):
            pass

        async def aclose(self):
            return None

    monkeypatch.setattr(wrapper, "stdin_reader", fake_reader)
    monkeypatch.setattr(wrapper.asyncio, "create_task", fake_create_task)
    monkeypatch.setattr(wrapper, "ResilientHttpClient", DummyResilient)
    monkeypatch.setattr(wrapper, "make_request", AsyncMock())

    await wrapper.main_async(wrapper.Settings("http://x/mcp", None))
    assert wrapper.shutting_down()


@pytest.mark.asyncio
async def test_main_async_worker_skips_make_request_when_shutting_down(monkeypatch):
    """Cover worker branch when shutdown is observed before calling make_request."""
    wrapper._shutdown.clear()

    worker_checked = asyncio.Event()

    async def fake_reader(queue):
        await queue.put({"foo": "bar"})
        # Ensure the worker had a chance to observe shutdown before we send EOF.
        await asyncio.wait_for(worker_checked.wait(), timeout=1)
        await queue.put(None)

    # First two calls are the main loop's `while not shutting_down()` checks.
    # Third call is the worker's `if not shutting_down()` guard.
    calls = {"n": 0}

    def seq_shutting_down():
        calls["n"] += 1
        if calls["n"] == 3:
            worker_checked.set()
        return calls["n"] >= 3

    monkeypatch.setattr(wrapper, "shutting_down", seq_shutting_down)
    monkeypatch.setattr(wrapper, "stdin_reader", fake_reader)
    monkeypatch.setattr(wrapper, "make_request", AsyncMock())

    class DummyResilient:
        def __init__(self, *a, **k):
            pass

        async def aclose(self):
            return None

    monkeypatch.setattr(wrapper, "ResilientHttpClient", DummyResilient)

    await wrapper.main_async(wrapper.Settings("http://x/mcp", None, concurrency=1))
    assert wrapper.make_request.await_count == 0


# -------------------
# _install_signal_handlers runs (no-op on unsupported platforms)
# -------------------
def test_install_signal_handlers_runs():
    loop = asyncio.new_event_loop()
    try:
        wrapper._install_signal_handlers(loop)
    finally:
        loop.close()


def test_install_signal_handlers_sig_none_and_notimplemented(monkeypatch):
    # Cover both the `sig is None` branch and suppression of NotImplementedError.
    calls = {"n": 0}

    class DummyLoop:
        def add_signal_handler(self, *_a, **_k):
            calls["n"] += 1
            raise NotImplementedError

    monkeypatch.setattr(wrapper.signal, "SIGINT", None, raising=False)
    monkeypatch.setattr(wrapper.signal, "SIGTERM", None, raising=False)
    wrapper._install_signal_handlers(DummyLoop())
    assert calls["n"] == 0

    # Restore real signals for the NotImplementedError suppression path.
    import signal as _signal

    monkeypatch.setattr(wrapper.signal, "SIGINT", _signal.SIGINT, raising=False)
    monkeypatch.setattr(wrapper.signal, "SIGTERM", _signal.SIGTERM, raising=False)
    wrapper._install_signal_handlers(DummyLoop())


def test_main_runs_with_patched_deps(monkeypatch):
    wrapper._shutdown.clear()

    monkeypatch.setattr(wrapper, "parse_args", lambda: wrapper.Settings("http://x/mcp", None, log_level="DEBUG"))
    monkeypatch.setattr(wrapper, "_install_signal_handlers", lambda _loop: None)

    async def fake_main_async(_settings):
        await asyncio.sleep(0)

    monkeypatch.setattr(wrapper, "main_async", fake_main_async)
    # Avoid altering global event loop in the test process.
    monkeypatch.setattr(wrapper.asyncio, "set_event_loop", lambda _loop: None)

    wrapper.main()


def test_main_runs_with_logging_disabled(monkeypatch):
    """Cover main() branches when logging is disabled."""
    wrapper._shutdown.clear()

    monkeypatch.setattr(wrapper, "parse_args", lambda: wrapper.Settings("http://x/mcp", None, log_level=None))
    monkeypatch.setattr(wrapper, "_install_signal_handlers", lambda _loop: None)

    async def fake_main_async(_settings):
        await asyncio.sleep(0)

    monkeypatch.setattr(wrapper, "main_async", fake_main_async)
    monkeypatch.setattr(wrapper.asyncio, "set_event_loop", lambda _loop: None)

    wrapper.main()
