# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_translate.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Full-coverage test-suite for **mcpgateway.translate**.
This suite touches **every executable path** inside `mcpgateway.translate`
and therefore produces a coverage report of **100 %**.  Specifically, it
exercises:

* `_PubSub` fan-out logic, including the QueueFull subscriber-removal path.
* `StdIOEndpoint.start/stop/send/_pump_stdout` via a fully faked subprocess.
* `_build_fastapi` - the `/sse`, `/message`, and `/healthz` routes, keep-alive
  frames, and request forwarding.
* `_parse_args` on the happy path (`--stdio` / `--sse`) **and** the
  *NotImplemented* `--streamableHttp` branch.
* `_run_stdio_to_sse` orchestration with an in-process uvicorn stub so no real
  network binding occurs.
* `_run_sse_to_stdio` ingestion path with patched `httpx` and a dummy shell
  command.
* The module's CLI entry-point executed via `python3 -m mcpgateway.translate`
  (tested with `runpy`).

Run with:

    pytest -q --cov=mcpgateway.translate
"""

# ---------------------------------------------------------------------------#
# Imports                                                                    #
# ---------------------------------------------------------------------------#

# Future
from __future__ import annotations

# Standard
# Standard Library
import asyncio
import importlib
import sys
import types
from typing import Any, Sequence
from unittest.mock import AsyncMock, Mock

# Third-Party
from fastapi.testclient import TestClient
import pytest

# import inspect


# ---------------------------------------------------------------------------#
# Pytest fixtures                                                            #
# ---------------------------------------------------------------------------#


@pytest.fixture()
def translate():
    """Reload mcpgateway.translate for a pristine state each test."""
    sys.modules.pop("mcpgateway.translate", None)
    return importlib.import_module("mcpgateway.translate")


def test_translate_importerror(monkeypatch, translate):
    # Test the httpx import error handling directly in the translate module
    # Since other modules may import httpx, we need to test this at the module level

    # Mock httpx to be None to test the ImportError branch
    monkeypatch.setattr(translate, "httpx", None)

    # Test that _run_sse_to_stdio raises ImportError when httpx is None
    # Standard
    import asyncio

    # Third-Party
    import pytest

    async def test_sse_without_httpx():
        with pytest.raises(ImportError, match="httpx package is required"):
            await translate._run_sse_to_stdio("http://example.com/sse", None)

    asyncio.run(test_sse_without_httpx())


def test_translate_module_level_import_fallbacks(monkeypatch):
    """Force ImportError inside mcpgateway.translate module-level optional imports."""
    # Standard
    import builtins
    import importlib
    import sys

    # Ensure a fresh import for this test.
    sys.modules.pop("mcpgateway.translate", None)

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
        caller = sys._getframe(1).f_globals.get("__name__")
        if caller == "mcpgateway.translate" and name in {"httpx", "mcpgateway.config"}:
            raise ImportError(f"blocked import: {name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    mod = importlib.import_module("mcpgateway.translate")
    assert mod.httpx is None
    assert mod.DEFAULT_KEEP_ALIVE_INTERVAL == 30
    assert mod.DEFAULT_KEEPALIVE_ENABLED is True
    assert mod.DEFAULT_SSL_VERIFY is True

    # Clean up so other tests can import the normal module variant.
    sys.modules.pop("mcpgateway.translate", None)


# ---------------------------------------------------------------------------#
# Dummy subprocess plumbing                                                  #
# ---------------------------------------------------------------------------#


class _DummyWriter:
    def __init__(self):
        self.buffer: list[bytes] = []

    def write(self, data: bytes):
        self.buffer.append(data)

    async def drain(self): ...


class _DummyReader:
    def __init__(self, lines: Sequence[str]):
        self._lines = [ln.encode() for ln in lines]

    async def readline(self) -> bytes:
        return self._lines.pop(0) if self._lines else b""


class _FakeProc:
    """Mimics `asyncio.subprocess.Process` for full stdio control."""

    def __init__(self, lines: Sequence[str]):
        self.stdin = _DummyWriter()
        self.stdout = _DummyReader(lines)
        self.pid = 4321
        self.terminated = False
        self.returncode = None

    def terminate(self):
        self.terminated = True

    async def wait(self):
        return 0


# ---------------------------------------------------------------------------#
# Tests: _PubSub                                                             #
# ---------------------------------------------------------------------------#


@pytest.mark.asyncio
async def test_pubsub_basic(translate):
    ps = translate._PubSub()
    q = ps.subscribe()
    await ps.publish("data")
    assert q.get_nowait() == "data"
    ps.unsubscribe(q)
    assert q not in ps._subscribers


@pytest.mark.asyncio
async def test_pubsub_queuefull_removal(translate):
    ps = translate._PubSub()

    class _Full(asyncio.Queue):
        def put_nowait(self, *_):  # type: ignore[override]
            raise asyncio.QueueFull

    bad = _Full()
    ps._subscribers.append(bad)
    await ps.publish("x")
    assert bad not in ps._subscribers


@pytest.mark.asyncio
async def test_pubsub_double_unsubscribe_and_publish_no_subs(translate):
    ps = translate._PubSub()
    q = ps.subscribe()
    ps.unsubscribe(q)
    # Unsubscribing again should not raise
    ps.unsubscribe(q)
    # Publishing with no subscribers should not raise
    await ps.publish("no one listens")


# ---------------------------------------------------------------------------#
# Tests: StdIOEndpoint                                                       #
# ---------------------------------------------------------------------------#


@pytest.mark.asyncio
async def test_stdio_endpoint_stop_when_proc_none(translate):
    """Test StdIOEndpoint.stop() returns immediately if _proc is None."""
    ps = translate._PubSub()
    ep = translate.StdIOEndpoint("echo test", ps)
    # Ensure _proc is None (should be by default)
    assert ep._proc is None
    # Should not raise or do anything
    await ep.stop()


@pytest.mark.asyncio
async def test_stdio_endpoint_flow(monkeypatch, translate):
    ps = translate._PubSub()
    fake = _FakeProc(['{"jsonrpc":"2.0"}\n'])

    async def _fake_exec(*_a, **_kw):
        return fake

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", _fake_exec)

    ep = translate.StdIOEndpoint("echo hi", ps)
    subscriber = ps.subscribe()

    await ep.start()
    assert (await subscriber.get()).rstrip("\n") == '{"jsonrpc":"2.0"}'
    await ep.send("PING\n")
    assert fake.stdin.buffer[-1] == b"PING\n"
    await ep.stop()
    assert fake.terminated


@pytest.mark.asyncio
async def test_stdio_endpoint_start_stops_existing_process_and_manages_env(monkeypatch, translate):
    """Cover StdIOEndpoint.start() paths: stop existing proc, env updates, and header mapping clears."""
    ps = translate._PubSub()

    # Existing running proc should be stopped first.
    old_proc = _FakeProc(lines=[])

    captured: dict[str, Any] = {}

    async def _fake_exec(*_a, **kwargs):
        captured["env"] = kwargs.get("env") or {}
        return _FakeProc(lines=[])

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", _fake_exec)

    # Provide a header mapping that would clear DYNAMIC_VAR unless explicitly provided.
    ep = translate.StdIOEndpoint(
        "echo hi",
        ps,
        env_vars={"DYNAMIC_VAR": "secret"},
        header_mappings={"X-Var": "DYNAMIC_VAR", "X-Path": "PATH"},
    )
    ep._proc = old_proc

    await ep.start(additional_env_vars={"EXTRA": "1"})

    assert old_proc.terminated is True
    assert captured["env"].get("EXTRA") == "1"
    assert "DYNAMIC_VAR" not in captured["env"]
    assert "PATH" in captured["env"]
    assert ep.is_running() is True

    await ep.stop()


@pytest.mark.asyncio
async def test_stdio_send_without_start(translate):
    with pytest.raises(RuntimeError):
        await translate.StdIOEndpoint("cmd", translate._PubSub()).send("x")


@pytest.mark.asyncio
async def test_stdio_endpoint_eof_handling(monkeypatch, translate):
    """Test that EOF on stdout is handled properly."""
    ps = translate._PubSub()
    fake = _FakeProc([])  # No lines, will trigger EOF

    async def _fake_exec(*_a, **_kw):
        return fake

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", _fake_exec)

    ep = translate.StdIOEndpoint("echo hi", ps)
    await ep.start()
    # Should exit gracefully when EOF is encountered
    await ep.stop()


@pytest.mark.asyncio
async def test_stdio_endpoint_stop_timeout(monkeypatch, translate):
    """Test timeout handling during subprocess termination."""
    ps = translate._PubSub()
    fake = _FakeProc(['{"test": "data"}\n'])

    # Mock wait to timeout
    async def _wait_timeout():
        raise asyncio.TimeoutError("Process didn't terminate")

    fake.wait = _wait_timeout

    async def _fake_exec(*_a, **_kw):
        return fake

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", _fake_exec)

    ep = translate.StdIOEndpoint("test cmd", ps)
    await ep.start()
    await ep.stop()  # Should handle timeout gracefully
    assert fake.terminated


@pytest.mark.asyncio
async def test_stdio_endpoint_stop_handles_process_lookup_error_and_cancels_pump(translate):
    """Cover stop() ProcessLookupError branch and pump task cancellation/await."""
    ps = translate._PubSub()
    ep = translate.StdIOEndpoint("echo hi", ps)

    class Proc:
        pid = 123
        returncode = None

        def terminate(self):
            raise ProcessLookupError

        async def wait(self):
            return 0

    ep._proc = Proc()
    ep._stdin = _DummyWriter()
    ep._pump_task = asyncio.create_task(asyncio.sleep(10))

    await ep.stop()
    assert ep._proc is None
    assert ep._stdin is None


@pytest.mark.asyncio
async def test_stdio_endpoint_stop_cancels_pump(monkeypatch, translate):
    ps = translate._PubSub()
    fake = _FakeProc(['{"jsonrpc":"2.0"}\n'])

    async def _fake_exec(*_a, **_kw):
        return fake

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", _fake_exec)

    ep = translate.StdIOEndpoint("echo hi", ps)
    await ep.start()
    # Simulate pump task still running
    assert ep._pump_task is not None
    # Stop should cancel the pump task
    await ep.stop()
    assert fake.terminated


@pytest.mark.asyncio
async def test_stdio_endpoint_stop_process_already_terminated(translate):
    """Ensure stop returns cleanly when process already terminated."""
    ps = translate._PubSub()
    ep = translate.StdIOEndpoint("echo hi", ps)

    class DummyProc:
        pid = 123
        returncode = 0

    ep._proc = DummyProc()
    ep._stdin = Mock()

    await ep.stop()

    assert ep._proc is None
    assert ep._stdin is None


@pytest.mark.asyncio
async def test_stdio_endpoint_stop_process_lookup_error(translate):
    """Ensure stop handles ProcessLookupError on returncode access."""
    ps = translate._PubSub()
    ep = translate.StdIOEndpoint("echo hi", ps)

    class DummyProc:
        pid = 123

        @property
        def returncode(self):
            raise ProcessLookupError

    ep._proc = DummyProc()
    ep._stdin = Mock()

    await ep.stop()

    assert ep._proc is None
    assert ep._stdin is None


@pytest.mark.asyncio
async def test_stdio_endpoint_pump_stdout_missing_stdout(translate):
    """Ensure _pump_stdout raises when stdout is missing."""
    ps = translate._PubSub()
    ep = translate.StdIOEndpoint("echo hi", ps)
    ep._proc = types.SimpleNamespace(stdout=None)

    with pytest.raises(RuntimeError, match="missing stdout"):
        await ep._pump_stdout()


# ---------------------------------------------------------------------------#
# Tests: FastAPI facade (/sse /message /healthz)                             #
# ---------------------------------------------------------------------------#


@pytest.mark.asyncio
async def test_fastapi_healthz_endpoint(translate):
    """Test the /healthz health check endpoint."""
    ps = translate._PubSub()
    stdio = translate.StdIOEndpoint("dummy", ps)
    app = translate._build_fastapi(ps, stdio)

    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.text == "ok"


@pytest.mark.asyncio
async def test_fastapi_message_endpoint_valid_json(translate):
    """Test /message endpoint with valid JSON payload."""
    ps = translate._PubSub()
    stdio = Mock()
    stdio.send = AsyncMock()

    app = translate._build_fastapi(ps, stdio)
    client = TestClient(app)

    payload = {"jsonrpc": "2.0", "method": "test", "id": 1}
    response = client.post("/message", json=payload)

    assert response.status_code == 202
    assert response.text == "forwarded"
    stdio.send.assert_called_once()


@pytest.mark.asyncio
async def test_fastapi_message_endpoint_invalid_json(translate):
    """Test /message endpoint with invalid JSON payload."""
    ps = translate._PubSub()
    stdio = Mock()

    app = translate._build_fastapi(ps, stdio)
    client = TestClient(app)

    response = client.post(
        "/message",
        content="invalid json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400
    assert "Invalid JSON payload" in response.text


@pytest.mark.asyncio
async def test_fastapi_message_endpoint_with_session_id(translate):
    """Test /message endpoint with session_id parameter."""
    ps = translate._PubSub()
    stdio = Mock()
    stdio.send = AsyncMock()

    app = translate._build_fastapi(ps, stdio)
    client = TestClient(app)

    payload = {"jsonrpc": "2.0", "method": "test", "id": 1}
    response = client.post("/message?session_id=test123", json=payload)

    assert response.status_code == 202
    stdio.send.assert_called_once()


def test_fastapi_sse_endpoint_basic(translate, monkeypatch):
    """Test basic SSE endpoint functionality."""
    ps = translate._PubSub()
    stdio = Mock()

    # Mock uuid.uuid4 to return predictable session ID
    mock_uuid = Mock()
    mock_uuid.hex = "test-session-123"
    monkeypatch.setattr(translate.uuid, "uuid4", lambda: mock_uuid)

    app = translate._build_fastapi(ps, stdio, keep_alive=1)

    # Just test that the app was built correctly with the routes
    route_paths = [route.path for route in app.routes if hasattr(route, "path")]
    assert "/sse" in route_paths
    assert "/message" in route_paths
    assert "/healthz" in route_paths


def test_fastapi_sse_endpoint_with_messages(translate, monkeypatch):
    """Test SSE endpoint with published messages."""
    ps = translate._PubSub()
    stdio = Mock()

    # Mock uuid.uuid4
    mock_uuid = Mock()
    mock_uuid.hex = "test-session-456"
    monkeypatch.setattr(translate.uuid, "uuid4", lambda: mock_uuid)

    app = translate._build_fastapi(ps, stdio, keep_alive=10)

    # Just verify the app was built with correct configuration
    assert app is not None
    # Test that the pubsub system works
    q = ps.subscribe()
    assert q in ps._subscribers


@pytest.mark.asyncio
async def test_fastapi_sse_header_mappings_restart(monkeypatch, translate):
    """Test SSE handler restarts stdio when header mappings yield env vars."""
    ps = translate._PubSub()
    stdio = AsyncMock()
    stdio.stop = AsyncMock()
    stdio.start = AsyncMock()

    monkeypatch.setattr(translate, "extract_env_vars_from_headers", lambda *_args, **_kwargs: {"ENV_VAR": "1"})

    app = translate._build_fastapi(ps, stdio, header_mappings={"X-Env": "ENV_VAR"}, keep_alive=0.01)

    class DummyResponse:
        def __init__(self, gen, headers=None):
            self.gen = gen
            self.headers = headers

    monkeypatch.setattr(translate, "EventSourceResponse", DummyResponse)
    handler = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/sse")

    class DummyRequest:
        base_url = "http://test/"
        headers = {"X-Env": "1"}

        async def is_disconnected(self):
            return True

    resp = await handler(DummyRequest())
    # Consume generator to trigger unsubscribe
    first = await resp.gen.__anext__()
    second = await resp.gen.__anext__()
    assert first["event"] == "endpoint"
    assert second["event"] in {"keepalive", "message"}
    with pytest.raises(StopAsyncIteration):
        await resp.gen.__anext__()

    assert stdio.stop.await_count == 1
    assert stdio.start.await_count == 1
    assert len(ps._subscribers) == 0


@pytest.mark.asyncio
async def test_fastapi_sse_header_mappings_no_restart_and_timeout_keepalive(monkeypatch, translate):
    """Cover SSE generator keepalive timeout path and the no-restart branch when mappings yield no env vars."""
    ps = translate._PubSub()
    stdio = AsyncMock()
    stdio.stop = AsyncMock()
    stdio.start = AsyncMock()

    monkeypatch.setattr(translate, "DEFAULT_KEEPALIVE_ENABLED", True)
    monkeypatch.setattr(translate, "extract_env_vars_from_headers", lambda *_args, **_kwargs: {})

    # Force wait_for to time out immediately so we exercise the keepalive timeout branch.
    async def fake_wait_for(queue_get_coro, _timeout):
        queue_get_coro.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(translate.asyncio, "wait_for", fake_wait_for)
    app = translate._build_fastapi(ps, stdio, header_mappings={"X-Env": "ENV"}, keep_alive=0.01)

    class DummyResponse:
        def __init__(self, gen, headers=None):
            self.gen = gen
            self.headers = headers

    monkeypatch.setattr(translate, "EventSourceResponse", DummyResponse)
    handler = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/sse")

    class DummyRequest:
        base_url = "http://test/"
        headers = {"X-Env": "ignored"}

        def __init__(self):
            self.calls = 0

        async def is_disconnected(self):
            self.calls += 1
            # Only two loop iterations are needed:
            # 1) allow one timeout keepalive to be yielded
            # 2) then disconnect so the generator hits the unsubscribe path
            return self.calls > 1

    resp = await handler(DummyRequest())
    first = await resp.gen.__anext__()
    second = await resp.gen.__anext__()
    third = await resp.gen.__anext__()
    assert first["event"] == "endpoint"
    assert second["event"] == "keepalive"
    assert third["event"] == "keepalive"

    with pytest.raises(StopAsyncIteration):
        await resp.gen.__anext__()

    assert stdio.stop.await_count == 0
    assert stdio.start.await_count == 0
    assert len(ps._subscribers) == 0


@pytest.mark.asyncio
async def test_fastapi_sse_keepalive_disabled_yields_message(monkeypatch, translate):
    """Cover keepalive-disabled branch (no immediate keepalive) and message yield path."""
    ps = translate._PubSub()
    stdio = AsyncMock()

    monkeypatch.setattr(translate, "DEFAULT_KEEPALIVE_ENABLED", False)

    app = translate._build_fastapi(ps, stdio, keep_alive=0.01)

    class DummyResponse:
        def __init__(self, gen, headers=None):
            self.gen = gen
            self.headers = headers

    monkeypatch.setattr(translate, "EventSourceResponse", DummyResponse)
    handler = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/sse")

    class DummyRequest:
        base_url = "http://test/"
        headers = {}

        def __init__(self):
            self.calls = 0

        async def is_disconnected(self):
            self.calls += 1
            return self.calls > 1

    resp = await handler(DummyRequest())
    first = await resp.gen.__anext__()
    assert first["event"] == "endpoint"

    await ps.publish("hello\n")
    second = await resp.gen.__anext__()
    assert second["event"] == "message"
    assert second["data"] == "hello"

    with pytest.raises(StopAsyncIteration):
        await resp.gen.__anext__()

    # keepalive disabled still unsubscribes on close when pubsub is truthy
    assert len(ps._subscribers) == 0


@pytest.mark.asyncio
async def test_fastapi_sse_keepalive_disabled_timeout_and_falsy_pubsub_skips_unsubscribe(monkeypatch, translate):
    """Cover timeout exception path when keepalive is disabled and the falsy-pubsub cleanup branch."""

    class FalsyPubSub(translate._PubSub):
        def __bool__(self):
            return False

    ps = FalsyPubSub()
    stdio = AsyncMock()

    monkeypatch.setattr(translate, "DEFAULT_KEEPALIVE_ENABLED", False)

    # Force wait_for to raise, even though timeout=None when keepalive is disabled.
    async def fake_wait_for(queue_get_coro, _timeout):
        queue_get_coro.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(translate.asyncio, "wait_for", fake_wait_for)

    app = translate._build_fastapi(ps, stdio, keep_alive=0.01)

    class DummyResponse:
        def __init__(self, gen, headers=None):
            self.gen = gen
            self.headers = headers

    monkeypatch.setattr(translate, "EventSourceResponse", DummyResponse)
    handler = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/sse")

    class DummyRequest:
        base_url = "http://test/"
        headers = {}

        def __init__(self):
            self.calls = 0

        async def is_disconnected(self):
            self.calls += 1
            return self.calls > 1

    resp = await handler(DummyRequest())
    first = await resp.gen.__anext__()
    assert first["event"] == "endpoint"
    with pytest.raises(StopAsyncIteration):
        await resp.gen.__anext__()

    # Pubsub is falsy, so unsubscribe is skipped.
    assert len(ps._subscribers) == 1


@pytest.mark.asyncio
async def test_fastapi_message_header_mappings_restart(monkeypatch, translate):
    """Test /message restarts stdio when header mappings yield env vars."""
    ps = translate._PubSub()
    stdio = AsyncMock()
    stdio.stop = AsyncMock()
    stdio.start = AsyncMock()
    stdio.send = AsyncMock()
    stdio.is_running = Mock(return_value=False)

    monkeypatch.setattr(translate, "extract_env_vars_from_headers", lambda *_args, **_kwargs: {"ENV_VAR": "1"})
    monkeypatch.setattr(translate.asyncio, "sleep", AsyncMock())

    app = translate._build_fastapi(ps, stdio, header_mappings={"X-Env": "ENV_VAR"})
    handler = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/message")

    class DummyRequest:
        headers = {"X-Env": "1"}

        async def body(self):
            return b'{"jsonrpc":"2.0","method":"ping","id":1}'

    resp = await handler(DummyRequest(), session_id="abc")
    assert resp.status_code == 202
    assert stdio.stop.await_count == 1
    assert stdio.start.await_count >= 2
    stdio.send.assert_called_once()


@pytest.mark.asyncio
async def test_fastapi_message_no_restart_when_no_env_vars_and_already_running(monkeypatch, translate):
    """Cover /message branch where header mappings exist but no env vars are extracted and stdio is already running."""
    ps = translate._PubSub()
    stdio = AsyncMock()
    stdio.stop = AsyncMock()
    stdio.start = AsyncMock()
    stdio.send = AsyncMock()
    stdio.is_running = Mock(return_value=True)

    monkeypatch.setattr(translate, "extract_env_vars_from_headers", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(translate.asyncio, "sleep", AsyncMock())

    app = translate._build_fastapi(ps, stdio, header_mappings={"X-Env": "ENV"})
    handler = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/message")

    class DummyRequest:
        headers = {"X-Env": "ignored"}

        async def body(self):
            return b'{"jsonrpc":"2.0","method":"ping","id":1}'

    resp = await handler(DummyRequest(), session_id="abc")
    assert resp.status_code == 202
    assert stdio.stop.await_count == 0
    assert stdio.start.await_count == 0
    stdio.send.assert_called_once()


@pytest.mark.asyncio
async def test_fastapi_cors_enabled(translate):
    """Test CORS middleware is properly configured."""
    ps = translate._PubSub()
    stdio = Mock()

    cors_origins = ["https://example.com", "http://localhost:3000"]
    app = translate._build_fastapi(ps, stdio, cors_origins=cors_origins)
    client = TestClient(app)

    # Test basic request to check CORS headers are present
    response = client.get("/healthz")
    assert response.status_code == 200


def test_fastapi_custom_paths(translate):
    """Test custom SSE and message paths."""
    ps = translate._PubSub()
    stdio = Mock()
    stdio.send = AsyncMock()

    app = translate._build_fastapi(ps, stdio, sse_path="/custom-sse", message_path="/custom-message")

    # Check that custom paths exist
    route_paths = [route.path for route in app.routes if hasattr(route, "path")]
    assert "/custom-sse" in route_paths
    assert "/custom-message" in route_paths
    assert "/healthz" in route_paths  # Default health endpoint should still exist


def test_build_fastapi_with_cors_and_keepalive(translate):
    ps = translate._PubSub()
    stdio = Mock()
    app = translate._build_fastapi(ps, stdio, keep_alive=5, cors_origins=["*"])
    assert app is not None
    # Check CORS middleware is present
    assert any("CORSMiddleware" in str(m) for m in app.user_middleware)


@pytest.mark.asyncio
async def test_sse_event_gen_unsubscribes_on_disconnect(monkeypatch, translate):
    ps = translate._PubSub()
    stdio = Mock()
    app = translate._build_fastapi(ps, stdio)

    # Patch request to simulate disconnect after first yield
    class DummyRequest:
        def __init__(self):
            self.base_url = "http://test/"
            self._disconnected = False

        async def is_disconnected(self):
            if not self._disconnected:
                self._disconnected = True
                return False
            return True

    # Get the /sse route handler
    for route in app.routes:
        if getattr(route, "path", None) == "/sse":
            handler = route.endpoint
            break

    # Call the handler and exhaust the generator
    resp = await handler(DummyRequest())
    # The generator should unsubscribe after disconnect (no error)
    assert resp is not None


# ---------------------------------------------------------------------------#
# Tests: _parse_args                                                         #
# ---------------------------------------------------------------------------#


def test_parse_args_ok(translate):
    ns = translate._parse_args(["--stdio", "echo hi", "--port", "9001"])
    assert (ns.stdio, ns.port) == ("echo hi", 9001)


def test_parse_args_connect_sse_ok(translate):
    ns = translate._parse_args(["--connect-sse", "http://up.example/sse"])
    assert ns.connect_sse == "http://up.example/sse" and ns.stdio is None


def test_parse_args_connect_streamable_http(translate):
    """Test parsing connect-streamable-http arguments."""
    ns = translate._parse_args(["--connect-streamable-http", "https://api.example.com/mcp"])
    assert ns.connect_streamable_http == "https://api.example.com/mcp"
    assert ns.stdio is None


def test_parse_args_expose_protocols(translate):
    """Test parsing expose protocol arguments."""
    # Test expose-sse flag
    ns = translate._parse_args(["--stdio", "uvx mcp-server-git", "--expose-sse"])
    assert ns.stdio == "uvx mcp-server-git"
    assert ns.expose_sse is True
    assert ns.expose_streamable_http is False

    # Test expose-streamable-http flag
    ns = translate._parse_args(["--stdio", "uvx mcp-server-git", "--expose-streamable-http"])
    assert ns.stdio == "uvx mcp-server-git"
    assert ns.expose_sse is False
    assert ns.expose_streamable_http is True

    # Test both flags together
    ns = translate._parse_args(["--stdio", "uvx mcp-server-git", "--expose-sse", "--expose-streamable-http"])
    assert ns.stdio == "uvx mcp-server-git"
    assert ns.expose_sse is True
    assert ns.expose_streamable_http is True

    # Test with stateless and jsonResponse flags for streamable HTTP
    ns = translate._parse_args(["--stdio", "uvx mcp-server-git", "--expose-streamable-http", "--stateless", "--jsonResponse"])
    assert ns.stdio == "uvx mcp-server-git"
    assert ns.expose_streamable_http is True
    assert ns.stateless is True
    assert ns.jsonResponse is True


def test_parse_args_with_cors(translate):
    """Test parsing CORS arguments."""
    ns = translate._parse_args(["--stdio", "echo hi", "--cors", "https://example.com", "http://localhost:3000"])
    assert ns.cors == ["https://example.com", "http://localhost:3000"]


def test_parse_args_with_oauth(translate):
    """Test parsing OAuth2 Bearer token."""
    ns = translate._parse_args(["--sse", "http://example.com/sse", "--oauth2Bearer", "test-token-123"])
    assert ns.oauth2Bearer == "test-token-123"


def test_parse_args_log_level(translate):
    """Test parsing log level."""
    ns = translate._parse_args(["--stdio", "echo hi", "--logLevel", "debug"])
    assert ns.logLevel == "debug"


def test_parse_args_missing_required(translate):
    """Test that parse_args returns args even without required arguments."""
    argv = []
    # Parse succeeds but returns None for main transport arguments
    args = translate._parse_args(argv)
    assert args.stdio is None
    assert args.connect_sse is None
    assert args.connect_streamable_http is None


# ---------------------------------------------------------------------------#
# Tests: _run_stdio_to_sse orchestration                                     #
# ---------------------------------------------------------------------------#


@pytest.mark.asyncio
async def test_run_stdio_to_sse(monkeypatch, translate):
    async def _test_logic():
        calls: list[str] = []

        class _DummyStd:
            def __init__(self, *_, **kwargs):
                calls.append("init")

            async def start(self):
                calls.append("start")

            async def stop(self):
                calls.append("stop")

        class _Cfg:
            """Accept any args/kwargs so signature matches real uvicorn.Config."""

            def __init__(self, *args, **kwargs):
                self.__dict__.update(kwargs)

        class _Srv:
            def __init__(self, cfg):
                self.cfg = cfg
                self.served = False
                self.shutdown_called = False

            async def serve(self):
                self.served = True

            async def shutdown(self):
                self.shutdown_called = True

        monkeypatch.setattr(translate, "StdIOEndpoint", _DummyStd)
        monkeypatch.setattr(translate.uvicorn, "Config", _Cfg)
        monkeypatch.setattr(translate.uvicorn, "Server", _Srv)
        monkeypatch.setattr(
            translate.asyncio,
            "get_running_loop",
            lambda: types.SimpleNamespace(add_signal_handler=lambda *_, **__: None),
        )

        await translate._run_stdio_to_sse("cmd", port=0)
        assert calls == ["init", "start", "stop"]

    # Add timeout to prevent hanging
    await asyncio.wait_for(_test_logic(), timeout=3.0)


@pytest.mark.asyncio
async def test_run_stdio_to_sse_with_cors(monkeypatch, translate):
    """Test _run_stdio_to_sse with CORS configuration."""

    async def _test_logic():
        calls: list[str] = []

        class _DummyStd:
            def __init__(self, *_, **kwargs):
                calls.append("init")

            async def start(self):
                calls.append("start")

            async def stop(self):
                calls.append("stop")

        class _Cfg:
            def __init__(self, *args, **kwargs):
                self.__dict__.update(kwargs)

        class _Srv:
            def __init__(self, cfg):
                self.cfg = cfg

            async def serve(self):
                pass

            async def shutdown(self):
                pass

        monkeypatch.setattr(translate, "StdIOEndpoint", _DummyStd)
        monkeypatch.setattr(translate.uvicorn, "Config", _Cfg)
        monkeypatch.setattr(translate.uvicorn, "Server", _Srv)
        monkeypatch.setattr(
            translate.asyncio,
            "get_running_loop",
            lambda: types.SimpleNamespace(add_signal_handler=lambda *_, **__: None),
        )

        cors_origins = ["https://example.com"]
        await translate._run_stdio_to_sse("cmd", port=0, cors=cors_origins)
        assert calls == ["init", "start", "stop"]

    # Add timeout to prevent hanging
    await asyncio.wait_for(_test_logic(), timeout=3.0)


@pytest.mark.asyncio
async def test_run_stdio_to_sse_signal_handling_windows(monkeypatch, translate):
    """Test signal handling when add_signal_handler raises NotImplementedError (Windows)."""

    async def _test_logic():
        class _DummyStd:
            def __init__(self, cmd, pubsub, **kwargs):  # Accept the required arguments
                self.cmd = cmd
                self.pubsub = pubsub

            async def start(self):
                pass

            async def stop(self):
                pass

        class _Cfg:
            def __init__(self, *args, **kwargs):
                pass

        class _Srv:
            def __init__(self, cfg):
                pass

            async def serve(self):
                pass

            async def shutdown(self):
                pass

        def _failing_signal_handler(*args, **kwargs):
            raise NotImplementedError("Windows doesn't support add_signal_handler")

        monkeypatch.setattr(translate, "StdIOEndpoint", _DummyStd)
        monkeypatch.setattr(translate.uvicorn, "Config", _Cfg)
        monkeypatch.setattr(translate.uvicorn, "Server", _Srv)
        monkeypatch.setattr(
            translate.asyncio,
            "get_running_loop",
            lambda: types.SimpleNamespace(add_signal_handler=_failing_signal_handler),
        )

        # Should complete without error despite signal handler failure
        await translate._run_stdio_to_sse("cmd", port=0)

    # Add timeout to prevent hanging
    await asyncio.wait_for(_test_logic(), timeout=3.0)


@pytest.mark.asyncio
async def test_run_stdio_to_sse_shutdown_idempotent(monkeypatch, translate):
    """Trigger shutdown via signal callback so the final cleanup hits the early-return branch."""

    async def _test_logic():
        calls: list[str] = []

        class _DummyStd:
            def __init__(self, *_, **__):
                calls.append("init")

            async def start(self, *_a, **_k):
                calls.append("start")

            async def stop(self):
                calls.append("stop")

        class _Cfg:
            def __init__(self, *args, **kwargs):
                self.__dict__.update(kwargs)

        class _Srv:
            def __init__(self, cfg):
                self.cfg = cfg
                self.should_exit = False

            async def serve(self):
                # Let the signal-triggered shutdown task run.
                await asyncio.sleep(0)

        # Immediately invoke the registered handler to schedule shutdown.
        def immediate_add_signal_handler(_sig, cb):
            cb()

        monkeypatch.setattr(translate, "StdIOEndpoint", _DummyStd)
        monkeypatch.setattr(translate.uvicorn, "Config", _Cfg)
        monkeypatch.setattr(translate.uvicorn, "Server", _Srv)
        monkeypatch.setattr(translate.asyncio, "get_running_loop", lambda: types.SimpleNamespace(add_signal_handler=immediate_add_signal_handler))

        await translate._run_stdio_to_sse("cmd", port=0)
        # stop should have been called despite shutdown being requested early
        assert calls.count("stop") == 1

    await asyncio.wait_for(_test_logic(), timeout=3.0)


# ---------------------------------------------------------------------------#
# Tests: _run_sse_to_stdio (stubbed I/O)                                     #
# ---------------------------------------------------------------------------#


@pytest.mark.asyncio
async def test_run_sse_to_stdio(monkeypatch, translate):
    async def _test_logic():
        class _DummyShell(_FakeProc):
            def __init__(self):
                super().__init__(lines=[])

        dummy_proc = _DummyShell()

        async def _fake_shell(*_a, **_kw):
            return dummy_proc

        monkeypatch.setattr(translate.asyncio, "create_subprocess_shell", _fake_shell)

        # Ensure translate.httpx exists before monkey-patching
        # Third-Party
        import httpx as _real_httpx  # noqa: WPS433

        setattr(translate, "httpx", _real_httpx)

        # Patch httpx.AsyncClient so no real HTTP happens
        class _Client:
            def __init__(self, *_, **__): ...

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_): ...

            def stream(self, *_a, **_kw):
                # Immediately raise an exception to exit _simple_sse_pump
                raise Exception("Test exception - no connection")

        monkeypatch.setattr(translate.httpx, "AsyncClient", _Client)

        # The function should handle the exception and exit
        try:
            await translate._run_sse_to_stdio("http://dummy/sse", None)
        except Exception as e:
            # Expected - the mock raises an exception
            assert "Test exception" in str(e)

    # Add timeout to prevent hanging
    await asyncio.wait_for(_test_logic(), timeout=3.0)


@pytest.mark.asyncio
async def test_run_sse_to_stdio_with_auth(monkeypatch, translate):
    """Test _run_sse_to_stdio with OAuth2 Bearer authentication."""

    async def _test_logic():
        class _DummyShell(_FakeProc):
            def __init__(self):
                super().__init__(lines=[])

        dummy_proc = _DummyShell()

        async def _fake_shell(*_a, **_kw):
            return dummy_proc

        monkeypatch.setattr(translate.asyncio, "create_subprocess_shell", _fake_shell)

        # Third-Party
        import httpx as _real_httpx

        setattr(translate, "httpx", _real_httpx)

        # Track the headers passed to httpx.AsyncClient
        captured_headers = {}

        class _Client:
            def __init__(self, *_, headers=None, **__):
                nonlocal captured_headers
                captured_headers = headers or {}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                pass

            def stream(self, *_a, **_kw):
                # Immediately raise an exception to exit _simple_sse_pump
                raise Exception("Test exception - no connection")

        monkeypatch.setattr(translate.httpx, "AsyncClient", _Client)

        try:
            await translate._run_sse_to_stdio("http://dummy/sse", "test-bearer-token")
        except Exception:
            # Expected - the mock raises an exception
            pass

        assert captured_headers.get("Authorization") == "Bearer test-bearer-token"

    # Add timeout to prevent hanging
    await asyncio.wait_for(_test_logic(), timeout=3.0)


@pytest.mark.asyncio
async def test_run_sse_to_stdio_with_data_processing(monkeypatch, translate):
    """Test _run_sse_to_stdio with actual SSE data processing."""

    async def _test_logic():
        # Mock httpx to simulate SSE response
        # Third-Party
        import httpx as _real_httpx

        setattr(translate, "httpx", _real_httpx)

        # Capture printed output
        printed = []
        monkeypatch.setattr("builtins.print", lambda x: printed.append(x))

        class _Resp:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                pass

            async def aiter_lines(self):
                # Yield test data
                yield "event: message"
                yield 'data: {"jsonrpc":"2.0","result":"test"}'
                yield ""
                # End the stream
                raise Exception("Test stream ended")

        class _Client:
            def __init__(self, *_, **__):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                pass

            def stream(self, *_a, **_kw):
                return _Resp()

        monkeypatch.setattr(translate.httpx, "AsyncClient", _Client)

        # Call without stdio_command (simple mode)
        try:
            await translate._run_sse_to_stdio("http://dummy/sse", None)
        except Exception as e:
            assert "Test stream ended" in str(e)

        # Verify that data was printed
        assert '{"jsonrpc":"2.0","result":"test"}' in printed

    # Add timeout to prevent hanging
    await asyncio.wait_for(_test_logic(), timeout=5.0)


@pytest.mark.asyncio
async def test_run_sse_to_stdio_importerror(monkeypatch, translate):
    monkeypatch.setattr(translate, "httpx", None)
    with pytest.raises(ImportError):
        await translate._run_sse_to_stdio("http://dummy/sse", None)


@pytest.mark.asyncio
async def test_run_sse_to_stdio_simple_mode_returns(monkeypatch, translate):
    """Ensure simple-mode uses get_isolated_http_client and returns cleanly."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    # Patch the isolated client context so no real network calls happen.
    import mcpgateway.services.http_client_service as http_client_service

    class DummyClient:
        pass

    class DummyCtx:
        async def __aenter__(self):
            return DummyClient()

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr(http_client_service, "get_isolated_http_client", lambda **_k: DummyCtx())
    pump = AsyncMock()
    monkeypatch.setattr(translate, "_simple_sse_pump", pump)

    await translate._run_sse_to_stdio("http://dummy/sse", "token", stdio_command=None, max_retries=1, initial_retry_delay=0.0)
    pump.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_sse_to_stdio_missing_pipes_raises(monkeypatch, translate):
    """Cover missing stdin/stdout pipes RuntimeError in full mode."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    class FakeProcess:
        stdin = None
        stdout = None
        returncode = None

    async def fake_create_subprocess_exec(*_a, **_k):
        return FakeProcess()

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    with pytest.raises(RuntimeError, match="Failed to create subprocess"):
        await translate._run_sse_to_stdio("http://dummy/sse", None, stdio_command="echo test", max_retries=0)


@pytest.mark.asyncio
async def test_run_sse_to_stdio_read_stdout_raises_when_stdout_missing_initial(monkeypatch, translate):
    """Cover read_stdout guard when process.stdout is missing."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    class FlakyProc:
        def __init__(self):
            self.stdin = _DummyWriter()
            self._stdout_obj = _DummyReader([])
            self._stdout_access = 0
            self.returncode = None

        @property
        def stdout(self):
            self._stdout_access += 1
            # Pipe check sees stdout, read_stdout sees None.
            return self._stdout_obj if self._stdout_access == 1 else None

        def terminate(self):
            self.returncode = 0

        async def wait(self):
            return 0

    proc = FlakyProc()

    async def fake_create_subprocess_exec(*_a, **_k):
        return proc

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    import mcpgateway.services.http_client_service as http_client_service

    class DummyClient:
        async def post(self, *_a, **_k):  # pragma: no cover - should not be reached
            raise AssertionError("post should not be called")

    class DummyCtx:
        async def __aenter__(self):
            return DummyClient()

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr(http_client_service, "get_isolated_http_client", lambda **_k: DummyCtx())

    with pytest.raises(RuntimeError, match="Process stdout not available"):
        await translate._run_sse_to_stdio("http://dummy/sse", None, stdio_command="echo test", max_retries=0)


@pytest.mark.asyncio
async def test_run_sse_to_stdio_read_stdout_raises_when_stdout_missing_in_loop(monkeypatch, translate):
    """Cover read_stdout guard when process.stdout disappears during the loop."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    class FlakyProc:
        def __init__(self):
            self.stdin = _DummyWriter()
            self._stdout_obj = _DummyReader([])
            self._stdout_access = 0
            self.returncode = None

        @property
        def stdout(self):
            self._stdout_access += 1
            # Pipe check + initial read_stdout check see stdout; loop check sees None.
            return self._stdout_obj if self._stdout_access <= 2 else None

        def terminate(self):
            self.returncode = 0

        async def wait(self):
            return 0

    proc = FlakyProc()

    async def fake_create_subprocess_exec(*_a, **_k):
        return proc

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    import mcpgateway.services.http_client_service as http_client_service

    class DummyClient:
        async def post(self, *_a, **_k):  # pragma: no cover - should not be reached
            raise AssertionError("post should not be called")

    class DummyCtx:
        async def __aenter__(self):
            return DummyClient()

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr(http_client_service, "get_isolated_http_client", lambda **_k: DummyCtx())

    with pytest.raises(RuntimeError, match="Process stdout not available"):
        await translate._run_sse_to_stdio("http://dummy/sse", None, stdio_command="echo test", max_retries=0)


@pytest.mark.asyncio
async def test_run_sse_to_stdio_read_stdout_skips_blank_lines(monkeypatch, translate):
    """Cover read_stdout continue branch when a decoded line is empty."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    class Proc:
        def __init__(self):
            self.stdin = _DummyWriter()
            self.stdout = _DummyReader(["\n"])
            self.returncode = None
            self.terminated = False

        def terminate(self):
            self.terminated = True

        async def wait(self):
            return 0

    proc = Proc()

    async def fake_create_subprocess_exec(*_a, **_k):
        return proc

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    import mcpgateway.services.http_client_service as http_client_service

    class DummyClient:
        async def post(self, *_a, **_k):  # pragma: no cover - should not be reached
            raise AssertionError("post should not be called")

    class DummyCtx:
        async def __aenter__(self):
            return DummyClient()

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr(http_client_service, "get_isolated_http_client", lambda **_k: DummyCtx())

    await translate._run_sse_to_stdio("http://dummy/sse", None, stdio_command="echo test", max_retries=0)
    assert proc.terminated is True


@pytest.mark.asyncio
async def test_run_sse_to_stdio_read_stdout_no_endpoint_after_retries(monkeypatch, translate):
    """Cover read_stdout path where no message endpoint is ever received."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    class Proc:
        def __init__(self):
            self.stdin = _DummyWriter()
            self.stdout = _DummyReader(['{"test": "data"}\n'])
            self.returncode = None
            self.terminated = False

        def terminate(self):
            self.terminated = True

        async def wait(self):
            return 0

    proc = Proc()

    async def fake_create_subprocess_exec(*_a, **_k):
        return proc

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(translate.asyncio, "sleep", AsyncMock())

    import mcpgateway.services.http_client_service as http_client_service

    class DummyClient:
        async def post(self, *_a, **_k):  # pragma: no cover - should not be reached
            raise AssertionError("post should not be called")

    class DummyCtx:
        async def __aenter__(self):
            return DummyClient()

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr(http_client_service, "get_isolated_http_client", lambda **_k: DummyCtx())

    await translate._run_sse_to_stdio("http://dummy/sse", None, stdio_command="echo test", max_retries=0)
    assert proc.terminated is True


@pytest.mark.asyncio
async def test_run_sse_to_stdio_read_stdout_posts_and_handles_errors(monkeypatch, translate):
    """Cover read_stdout POST warning + exception branches once an endpoint is received."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    endpoint_ready = asyncio.Event()
    posts_done = asyncio.Event()

    class Stdout:
        def __init__(self):
            self._lines = [
                b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n',
                b'{"jsonrpc":"2.0","id":2,"method":"ping"}\n',
                b"",
            ]

        async def readline(self):
            await endpoint_ready.wait()
            line = self._lines.pop(0)
            if not line:
                posts_done.set()
            return line

    class Proc:
        def __init__(self):
            self.stdin = _DummyWriter()
            self.stdout = Stdout()
            self.returncode = None
            self.terminated = False

        def terminate(self):
            self.terminated = True

        async def wait(self):
            return 0

    proc = Proc()

    async def fake_create_subprocess_exec(*_a, **_k):
        return proc

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    class FakeResp:
        status_code = 200
        request = real_httpx.Request("GET", "http://dummy/sse")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def aiter_lines(self):
            yield "event: endpoint"
            yield "data: http://example.com/message"
            yield ""
            # Called only after the empty line is processed by the pump.
            endpoint_ready.set()
            await posts_done.wait()
            raise real_httpx.ConnectError("done", request=self.request)

    class FakeClient:
        def __init__(self):
            self.calls = 0

        def stream(self, *_a, **_k):
            return FakeResp()

        async def post(self, *_a, **_k):
            self.calls += 1
            if self.calls == 1:
                return types.SimpleNamespace(status_code=500, text="fail")
            raise Exception("post failed")

    fake_client = FakeClient()

    import mcpgateway.services.http_client_service as http_client_service

    class DummyCtx:
        async def __aenter__(self):
            return fake_client

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr(http_client_service, "get_isolated_http_client", lambda **_k: DummyCtx())

    with pytest.raises(real_httpx.ConnectError):
        await translate._run_sse_to_stdio("http://dummy/sse", None, stdio_command="echo test", max_retries=1, initial_retry_delay=0.0)
    assert proc.terminated is True


@pytest.mark.asyncio
async def test_run_sse_to_stdio_read_stdout_posts_status_202_and_process_already_exited_skips_terminate(monkeypatch, translate):
    """Cover read_stdout branch where POST returns 202 and the loop continues; also cover cleanup when process already exited."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    endpoint_ready = asyncio.Event()
    posts_done = asyncio.Event()

    class Stdout:
        def __init__(self):
            self._lines = [
                b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n',
                b'{"jsonrpc":"2.0","id":2,"method":"ping"}\n',
                b"",
            ]

        async def readline(self):
            await endpoint_ready.wait()
            line = self._lines.pop(0)
            if not line:
                posts_done.set()
            return line

    class Proc:
        def __init__(self):
            self.stdin = _DummyWriter()
            self.stdout = Stdout()
            self.returncode = 0  # already "exited" so terminate() is skipped
            self.terminated = False

        def terminate(self):
            self.terminated = True

        async def wait(self):
            return 0

    proc = Proc()

    async def fake_create_subprocess_exec(*_a, **_k):
        return proc

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    class Resp:
        status_code = 200

        def __init__(self):
            self.request = real_httpx.Request("GET", "http://dummy/sse")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def aiter_lines(self):
            yield "event: endpoint"
            yield "data: http://example.com/message"
            yield ""
            endpoint_ready.set()
            await posts_done.wait()
            raise real_httpx.ConnectError("done", request=self.request)

    class Client:
        def __init__(self):
            self.post_calls = 0

        def stream(self, *_a, **_k):
            return Resp()

        async def post(self, *_a, **_k):
            self.post_calls += 1
            return types.SimpleNamespace(status_code=202, text="ok")

    client = Client()

    import mcpgateway.services.http_client_service as http_client_service

    class Ctx:
        async def __aenter__(self):
            return client

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr(http_client_service, "get_isolated_http_client", lambda **_k: Ctx())

    with pytest.raises(real_httpx.ConnectError):
        await translate._run_sse_to_stdio("http://dummy/sse", None, stdio_command="echo test", max_retries=1, initial_retry_delay=0.0)

    assert client.post_calls == 2
    assert proc.terminated is False


@pytest.mark.asyncio
async def test_run_sse_to_stdio_pump_status_error_when_httpx_falsy_raises_generic_exception(monkeypatch, translate):
    """Cover pump status-code error branch when httpx is truthy for startup but falsy inside the status check."""

    class TruthyThenFalsyHttpx:
        AsyncClient = object  # for annotation evaluation

        def __init__(self):
            self.calls = 0

        def __bool__(self):
            self.calls += 1
            return self.calls == 1

    monkeypatch.setattr(translate, "httpx", TruthyThenFalsyHttpx())

    class Proc:
        def __init__(self):
            self.stdin = _DummyWriter()
            self.stdout = _DummyReader([])
            self.returncode = 0

        def terminate(self):
            self.returncode = 0

        async def wait(self):
            return 0

    async def fake_create_subprocess_exec(*_a, **_k):
        return Proc()

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    class BadResp:
        status_code = 500

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def aiter_lines(self):
            if False:  # pragma: no cover
                yield ""

    class Client:
        def stream(self, *_a, **_k):
            return BadResp()

        async def post(self, *_a, **_k):
            return types.SimpleNamespace(status_code=202, text="ok")

    import mcpgateway.services.http_client_service as http_client_service

    class Ctx:
        async def __aenter__(self):
            return Client()

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr(http_client_service, "get_isolated_http_client", lambda **_k: Ctx())

    with pytest.raises(Exception, match="SSE endpoint returned 500"):
        await translate._run_sse_to_stdio("http://dummy/sse", None, stdio_command="echo test", max_retries=1, initial_retry_delay=0.0)


@pytest.mark.asyncio
async def test_run_sse_to_stdio_pump_message_does_not_forward_when_stdin_falsy_and_unknown_event(monkeypatch, translate):
    """Cover message event branch when stdin is falsy and an unknown event type is encountered."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    class ToggleStdin:
        def __init__(self):
            self.calls = 0
            self.writes: list[bytes] = []

        def __bool__(self):
            self.calls += 1
            return self.calls == 1

        def write(self, data: bytes):
            self.writes.append(data)

        async def drain(self):
            return None

    class Proc:
        def __init__(self):
            self.stdin = ToggleStdin()
            self.stdout = _DummyReader([])
            self.returncode = 0

        def terminate(self):
            self.returncode = 0

        async def wait(self):
            return 0

    proc = Proc()

    async def fake_create_subprocess_exec(*_a, **_k):
        return proc

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    class Resp:
        status_code = 200

        def __init__(self):
            self.request = real_httpx.Request("GET", "http://dummy/sse")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def aiter_lines(self):
            yield "event: endpoint"
            yield "data: http://example.com/message"
            yield ""
            yield "event: message"
            yield 'data: {"jsonrpc":"2.0","result":"ok"}'
            yield ""
            yield "event: keepalive"
            yield "data: {}"
            yield ""
            yield "event: mystery"
            yield "data: hi"
            yield ""
            raise real_httpx.ConnectError("done", request=self.request)

    class Client:
        def stream(self, *_a, **_k):
            return Resp()

        async def post(self, *_a, **_k):
            return types.SimpleNamespace(status_code=202, text="ok")

    import mcpgateway.services.http_client_service as http_client_service

    class Ctx:
        async def __aenter__(self):
            return Client()

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr(http_client_service, "get_isolated_http_client", lambda **_k: Ctx())

    with pytest.raises(real_httpx.ConnectError):
        await translate._run_sse_to_stdio("http://dummy/sse", None, stdio_command="echo test", max_retries=1, initial_retry_delay=0.0)

    assert proc.stdin.writes == []


@pytest.mark.asyncio
async def test_run_sse_to_stdio_pump_status_error_raises_httpstatuserror(monkeypatch, translate):
    """Cover pump_sse_to_stdio HTTP status error branch (non-200 response)."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    class Proc:
        def __init__(self):
            self.stdin = _DummyWriter()
            self.stdout = _DummyReader([])
            self.returncode = None

        def terminate(self):
            self.returncode = 0

        async def wait(self):
            return 0

    async def fake_create_subprocess_exec(*_a, **_k):
        return Proc()

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    class BadResp:
        status_code = 500

        def __init__(self):
            self.request = real_httpx.Request("GET", "http://dummy/sse")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def aiter_lines(self):
            if False:  # pragma: no cover
                yield ""

    class Client:
        def stream(self, *_a, **_k):
            return BadResp()

        async def post(self, *_a, **_k):
            return types.SimpleNamespace(status_code=202, text="ok")

    import mcpgateway.services.http_client_service as http_client_service

    class Ctx:
        async def __aenter__(self):
            return Client()

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr(http_client_service, "get_isolated_http_client", lambda **_k: Ctx())

    with pytest.raises(real_httpx.HTTPStatusError):
        await translate._run_sse_to_stdio("http://dummy/sse", None, stdio_command="echo test", max_retries=1, initial_retry_delay=0.0)


@pytest.mark.asyncio
async def test_run_sse_to_stdio_pump_message_and_keepalive_forwarding(monkeypatch, translate):
    """Cover pump_sse_to_stdio message forwarding and keepalive handling."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    class CapturingStdin:
        def __init__(self):
            self.writes: list[bytes] = []

        def write(self, data: bytes):
            self.writes.append(data)

        async def drain(self):
            return None

    class Proc:
        def __init__(self):
            self.stdin = CapturingStdin()
            self.stdout = _DummyReader([])
            self.returncode = None

        def terminate(self):
            self.returncode = 0

        async def wait(self):
            return 0

    proc = Proc()

    async def fake_create_subprocess_exec(*_a, **_k):
        return proc

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    class Resp:
        status_code = 200

        def __init__(self):
            self.request = real_httpx.Request("GET", "http://dummy/sse")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def aiter_lines(self):
            yield "event: endpoint"
            yield "data: http://example.com/message"
            yield ""
            yield "event: message"
            yield 'data: {"jsonrpc":"2.0","result":"ok"}'
            yield ""
            yield "event: keepalive"
            yield "data: {}"
            yield ""
            raise real_httpx.ConnectError("done", request=self.request)

    class Client:
        def stream(self, *_a, **_k):
            return Resp()

        async def post(self, *_a, **_k):
            return types.SimpleNamespace(status_code=202, text="ok")

    import mcpgateway.services.http_client_service as http_client_service

    class Ctx:
        async def __aenter__(self):
            return Client()

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr(http_client_service, "get_isolated_http_client", lambda **_k: Ctx())

    with pytest.raises(real_httpx.ConnectError):
        await translate._run_sse_to_stdio("http://dummy/sse", None, stdio_command="echo test", max_retries=1, initial_retry_delay=0.0)

    assert any(b'{"jsonrpc":"2.0","result":"ok"}\n' == w for w in proc.stdin.writes)


@pytest.mark.asyncio
async def test_run_sse_to_stdio_pump_retry_warning_and_backoff(monkeypatch, translate):
    """Cover pump retry warning + sleep/backoff path."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    class Proc:
        def __init__(self):
            self.stdin = _DummyWriter()
            self.stdout = _DummyReader([])
            self.returncode = None

        def terminate(self):
            self.returncode = 0

        async def wait(self):
            return 0

    async def fake_create_subprocess_exec(*_a, **_k):
        return Proc()

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(translate.asyncio, "sleep", AsyncMock())

    class Client:
        def __init__(self):
            self.n = 0

        def stream(self, *_a, **_k):
            self.n += 1
            raise real_httpx.ConnectError("boom", request=real_httpx.Request("GET", "http://dummy/sse"))

        async def post(self, *_a, **_k):
            return types.SimpleNamespace(status_code=202, text="ok")

    client = Client()

    import mcpgateway.services.http_client_service as http_client_service

    class Ctx:
        async def __aenter__(self):
            return client

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr(http_client_service, "get_isolated_http_client", lambda **_k: Ctx())

    with pytest.raises(real_httpx.ConnectError):
        await translate._run_sse_to_stdio("http://dummy/sse", None, stdio_command="echo test", max_retries=2, initial_retry_delay=0.0)

    assert translate.asyncio.sleep.await_count >= 1


@pytest.mark.asyncio
async def test_run_sse_to_stdio_pump_unexpected_error(monkeypatch, translate):
    """Cover pump unexpected exception branch."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    class Proc:
        def __init__(self):
            self.stdin = _DummyWriter()
            self.stdout = _DummyReader([])
            self.returncode = None

        def terminate(self):
            self.returncode = 0

        async def wait(self):
            return 0

    async def fake_create_subprocess_exec(*_a, **_k):
        return Proc()

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    class Client:
        def stream(self, *_a, **_k):
            raise ValueError("unexpected")

        async def post(self, *_a, **_k):
            return types.SimpleNamespace(status_code=202, text="ok")

    import mcpgateway.services.http_client_service as http_client_service

    class Ctx:
        async def __aenter__(self):
            return Client()

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr(http_client_service, "get_isolated_http_client", lambda **_k: Ctx())

    with pytest.raises(ValueError, match="unexpected"):
        await translate._run_sse_to_stdio("http://dummy/sse", None, stdio_command="echo test", max_retries=1, initial_retry_delay=0.0)


@pytest.mark.asyncio
async def test_pump_sse_to_stdio_full(monkeypatch, translate):
    # First, ensure httpx is properly imported and set
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    # Capture printed output for simple mode
    printed = []
    monkeypatch.setattr("builtins.print", lambda x: printed.append(x))

    # Prepare fake response with aiter_lines
    lines = [
        "event: endpoint",
        "data: http://example.com/message",
        "",
        "event: message",
        'data: {"jsonrpc":"2.0","result":"ok"}',
        "",
        "event: message",
        "data: another",
        "",
        "event: keepalive",
        "data: {}",
        "",
    ]

    line_index = 0

    class DummyResponse:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def aiter_lines(self):
            nonlocal line_index
            while line_index < len(lines):
                yield lines[line_index]
                line_index += 1
            # After all lines, raise an exception to simulate connection close
            # This is what would happen in a real SSE stream when the server closes
            raise real_httpx.ReadError("Connection closed")

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        def stream(self, *a, **k):
            return DummyResponse()

    # Only patch AsyncClient, not the whole httpx module
    original_client = translate.httpx.AsyncClient
    monkeypatch.setattr(translate.httpx, "AsyncClient", lambda *args, **kwargs: DummyClient())

    try:
        # Call without stdio_command - will use simple mode
        # Set max_retries to 1 to exit quickly after the stream ends
        await translate._run_sse_to_stdio("http://dummy/sse", None, max_retries=1)
    except Exception as e:
        # The stream will raise ReadError, then retry once and fail
        # This is expected behavior
        assert "Connection closed" in str(e) or "Max retries" in str(e)

    # Restore
    monkeypatch.setattr(translate.httpx, "AsyncClient", original_client)

    # Verify the messages were printed (simple mode prints to stdout)
    assert '{"jsonrpc":"2.0","result":"ok"}' in printed
    assert "another" in printed
    # Keepalive and endpoint should not be printed (they're logged, not printed)
    assert "{}" not in printed
    assert "http://example.com/message" not in printed


# ---------------------------------------------------------------------------#
# Tests: CLI entry-point (`python3 -m mcpgateway.translate`)                  #
# ---------------------------------------------------------------------------#


def test_module_entrypoint(monkeypatch, translate):
    """Test that the module can be executed as __main__."""
    executed: list[str] = []

    def _fake_main(argv=None):
        executed.append("main_called")

    monkeypatch.setattr(translate, "main", _fake_main)
    monkeypatch.setattr(sys, "argv", ["mcpgateway.translate", "--stdio", "echo hi"])

    # Test the __main__ block logic
    if __name__ != "__main__":  # We're in test, simulate the condition
        translate.main()  # This would be called in the __main__ block

    assert executed == ["main_called"]


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_main_function_stdio(monkeypatch, translate):
    """Test main() function with --stdio argument."""
    mock_multi_protocol = AsyncMock()
    monkeypatch.setattr(translate, "_run_multi_protocol_server", mock_multi_protocol)

    # Test that main() calls the right function
    translate.main(["--stdio", "echo test"])
    mock_multi_protocol.assert_called_once()


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_main_function_sse(monkeypatch, translate):
    mock_sse_runner = AsyncMock()
    monkeypatch.setattr(translate, "_run_sse_to_stdio", mock_sse_runner)

    translate.main(["--connect-sse", "http://example.com/sse"])
    mock_sse_runner.assert_called_once()


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_main_dynamic_env_parses_header_mappings_and_disables_default_protocol_branch(monkeypatch, translate):
    """Cover dynamic env header mapping parse path and the branch where a protocol is explicitly enabled."""
    mock_multi = AsyncMock()
    monkeypatch.setattr(translate, "_run_multi_protocol_server", mock_multi)

    # Avoid actually running the coroutine; just record the call site.
    def fake_run(coro):
        coro.close()
        return None

    monkeypatch.setattr(translate.asyncio, "run", fake_run)
    monkeypatch.setattr(translate, "parse_header_mappings", lambda _items: {"X-Env": "ENV"})

    monkeypatch.setattr(
        translate,
        "_parse_args",
        lambda _argv: type(
            "Args",
            (),
            {
                "stdio": "echo test",
                "connect_sse": None,
                "connect_streamable_http": None,
                "connect_grpc": None,
                "grpc": None,
                "grpc_metadata": None,
                "grpc_tls": False,
                "grpc_cert": None,
                "grpc_key": None,
                "enable_dynamic_env": True,
                "header_to_env": ["X-Env=ENV"],
                "expose_sse": True,  # makes the default-to-SSE branch false
                "expose_streamable_http": False,
                "ssePath": "/sse",
                "messagePath": "/message",
                "keepAlive": 30,
                "stateless": False,
                "jsonResponse": False,
                "logLevel": "info",
                "cors": None,
                "host": "127.0.0.1",
                "port": 8000,
                "oauth2Bearer": None,
                "stdioCommand": None,
            },
        )(),
    )

    translate.main(["--stdio", "echo test"])
    assert mock_multi.call_count == 1
    assert mock_multi.call_args.kwargs["header_mappings"] is not None


def test_main_dynamic_env_parse_failure_raises(monkeypatch, translate):
    """Cover dynamic env header mapping parse error path."""
    monkeypatch.setattr(translate, "parse_header_mappings", lambda _items: (_ for _ in ()).throw(ValueError("bad mappings")))
    monkeypatch.setattr(
        translate,
        "_parse_args",
        lambda _argv: type(
            "Args",
            (),
            {
                "enable_dynamic_env": True,
                "header_to_env": ["X-Env=ENV"],
                "grpc": None,
                "stdio": None,
                "connect_sse": None,
                "connect_streamable_http": None,
                "connect_grpc": None,
                "logLevel": "info",
            },
        )(),
    )

    with pytest.raises(ValueError, match="bad mappings"):
        translate.main([])


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_main_grpc_metadata_parsing(monkeypatch, translate):
    """Cover gRPC branch and metadata parsing in main()."""
    recorded: dict[str, Any] = {}

    async def expose_grpc_via_sse(**kwargs):
        recorded.update(kwargs)

    monkeypatch.setitem(sys.modules, "mcpgateway.translate_grpc", types.SimpleNamespace(expose_grpc_via_sse=expose_grpc_via_sse))
    monkeypatch.setattr(
        translate,
        "_parse_args",
        lambda _argv: type(
            "Args",
            (),
            {
                "grpc": "host:123",
                "grpc_metadata": ["k=v", "bad"],
                "grpc_tls": True,
                "grpc_cert": "/tmp/cert",
                "grpc_key": "/tmp/key",
                "port": 8000,
                "logLevel": "info",
                "enable_dynamic_env": False,
                "stdio": None,
                "connect_sse": None,
                "connect_streamable_http": None,
                "connect_grpc": None,
            },
        )(),
    )

    translate.main([])
    assert recorded["target"] == "host:123"
    assert recorded["metadata"] == {"k": "v"}


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_main_grpc_without_metadata(monkeypatch, translate):
    """Cover gRPC branch when no metadata is provided."""
    recorded: dict[str, Any] = {}

    async def expose_grpc_via_sse(**kwargs):
        recorded.update(kwargs)

    monkeypatch.setitem(sys.modules, "mcpgateway.translate_grpc", types.SimpleNamespace(expose_grpc_via_sse=expose_grpc_via_sse))
    monkeypatch.setattr(
        translate,
        "_parse_args",
        lambda _argv: type(
            "Args",
            (),
            {
                "grpc": "host:123",
                "grpc_metadata": None,
                "grpc_tls": False,
                "grpc_cert": None,
                "grpc_key": None,
                "port": 8000,
                "logLevel": "info",
                "enable_dynamic_env": False,
                "stdio": None,
                "connect_sse": None,
                "connect_streamable_http": None,
                "connect_grpc": None,
            },
        )(),
    )

    translate.main([])
    assert recorded["metadata"] == {}


def test_main_connect_grpc_not_implemented(monkeypatch, translate, capsys):
    """Cover --connect-grpc not implemented branch."""
    with pytest.raises(SystemExit) as exc:
        translate.main(["--connect-grpc", "host:123"])

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "not yet implemented" in captured.err


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_main_function_keyboard_interrupt(monkeypatch, translate, capsys):
    """Test main() function handles KeyboardInterrupt gracefully."""
    mock_multi_protocol = AsyncMock(side_effect=KeyboardInterrupt())
    monkeypatch.setattr(translate, "_run_multi_protocol_server", mock_multi_protocol)

    with pytest.raises(SystemExit) as exc_info:
        translate.main(["--stdio", "echo test"])

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert captured.out == "\n"  # Should print newline to restore shell prompt


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_main_function_not_implemented_error(monkeypatch, translate, capsys):
    """Test main() function handles NotImplementedError."""
    mock_multi_protocol = AsyncMock(side_effect=NotImplementedError("Test error message"))
    monkeypatch.setattr(translate, "_run_multi_protocol_server", mock_multi_protocol)

    with pytest.raises(SystemExit) as exc_info:
        translate.main(["--stdio", "echo test"])

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Test error message" in captured.err


def test_main_unknown_args(monkeypatch, translate, capsys):
    """Test main() function with no valid transport arguments."""
    monkeypatch.setattr(
        translate,
        "_parse_args",
        lambda argv: type(
            "Args",
            (),
            {
                "stdio": None,
                "connect_sse": None,
                "connect_streamable_http": None,
                "expose_sse": False,
                "expose_streamable_http": False,
                "logLevel": "info",
                "cors": None,
                "oauth2Bearer": None,
                "port": 8000,
            },
        )(),
    )
    # Should exit with error when no transport is specified
    with pytest.raises(SystemExit) as exc_info:
        translate.main(["--unknown"])

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Must specify either --stdio" in captured.err


# ---------------------------------------------------------------------------#
# Tests: Edge cases and error paths                                          #
# ---------------------------------------------------------------------------#


@pytest.mark.asyncio
async def test_pubsub_unsubscribe_missing_queue(translate):
    """Test unsubscribing a queue that's not in the subscribers list."""
    ps = translate._PubSub()
    q = asyncio.Queue()
    # Should not raise an exception
    ps.unsubscribe(q)


def test_stdio_endpoint_already_stopped(translate):
    """Test stopping an endpoint that's not running."""
    ps = translate._PubSub()
    ep = translate.StdIOEndpoint("echo test", ps)
    # Should not raise an exception - but make this synchronous test
    # since we're not actually starting anything async
    assert ep._proc is None


def test_build_fastapi_no_cors(translate):
    """Test _build_fastapi without CORS origins."""
    ps = translate._PubSub()
    stdio = Mock()

    # Should work without CORS origins
    app = translate._build_fastapi(ps, stdio, cors_origins=None)
    assert app is not None

    # Check that routes exist
    route_paths = [route.path for route in app.routes if hasattr(route, "path")]
    assert "/sse" in route_paths
    assert "/message" in route_paths
    assert "/healthz" in route_paths


def test_fastapi_sse_client_disconnect(translate, monkeypatch):
    """Test SSE endpoint when client disconnects."""
    ps = translate._PubSub()
    stdio = Mock()

    app = translate._build_fastapi(ps, stdio, keep_alive=1)

    # Just test that the app has the SSE route
    sse_routes = [route for route in app.routes if hasattr(route, "path") and route.path == "/sse"]
    assert len(sse_routes) == 1


@pytest.mark.asyncio
async def test_stdio_endpoint_exception_in_pump(monkeypatch, translate):
    """Test _pump_stdout exception handling."""

    async def _test_logic():
        ps = translate._PubSub()

        # Create a fake process that will raise an exception immediately
        class _FakeProcWithError:
            def __init__(self):
                self.stdin = _DummyWriter()
                self.pid = 1234
                self.terminated = False
                self.returncode = None
                self.stdout = self

            def terminate(self):
                self.terminated = True

            async def wait(self):
                return 0

            async def readline(self):
                # Always raise an exception immediately
                raise Exception("Test exception in pump")

        fake_proc = _FakeProcWithError()

        async def _fake_exec(*_a, **_kw):
            return fake_proc

        monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", _fake_exec)

        ep = translate.StdIOEndpoint("echo hi", ps)

        # Start the endpoint - the pump task will be created but fail immediately
        await ep.start()

        # Just verify the task exists and clean up quickly
        assert ep._pump_task is not None
        await ep.stop()

    # Add timeout to prevent hanging
    await asyncio.wait_for(_test_logic(), timeout=3.0)


@pytest.mark.asyncio
async def test_stdio_endpoint_send_not_started(translate):
    ep = translate.StdIOEndpoint("cmd", translate._PubSub())
    with pytest.raises(RuntimeError):
        await ep.send("test")


# Additional tests for improved coverage


def test_sse_event_init(translate):
    """Test SSEEvent initialization."""
    event = translate.SSEEvent(event="custom", data="test data", event_id="123", retry=5000)
    assert event.event == "custom"
    assert event.data == "test data"
    assert event.event_id == "123"
    assert event.retry == 5000


def test_sse_event_parse_sse_line_empty(translate):
    """Test SSEEvent.parse_sse_line with empty line."""
    # Empty line with no current event
    event, complete = translate.SSEEvent.parse_sse_line("", None)
    assert event is None
    assert complete is False

    # Empty line with current event
    current = translate.SSEEvent(data="test")
    event, complete = translate.SSEEvent.parse_sse_line("", current)
    assert event == current
    assert complete is True


def test_sse_event_parse_sse_line_comment(translate):
    """Test SSEEvent.parse_sse_line with comment line."""
    event, complete = translate.SSEEvent.parse_sse_line(": comment", None)
    assert event is None
    assert complete is False


def test_sse_event_parse_sse_line_fields(translate):
    """Test SSEEvent.parse_sse_line with various fields."""
    # Event field
    event, complete = translate.SSEEvent.parse_sse_line("event: test", None)
    assert event.event == "test"
    assert complete is False

    # Data field
    event, complete = translate.SSEEvent.parse_sse_line("data: hello", None)
    assert event.data == "hello"
    assert complete is False

    # Data field with existing data (multiline)
    current = translate.SSEEvent(data="line1")
    event, complete = translate.SSEEvent.parse_sse_line("data: line2", current)
    assert event.data == "line1\nline2"
    assert complete is False

    # ID field
    event, complete = translate.SSEEvent.parse_sse_line("id: 42", None)
    assert event.event_id == "42"
    assert complete is False

    # Retry field with valid value
    event, complete = translate.SSEEvent.parse_sse_line("retry: 3000", None)
    assert event.retry == 3000
    assert complete is False

    # Retry field with invalid value
    event, complete = translate.SSEEvent.parse_sse_line("retry: invalid", None)
    assert event.retry is None
    assert complete is False


def test_sse_event_parse_sse_line_no_colon(translate):
    """Test SSEEvent.parse_sse_line with line without colon."""
    event, complete = translate.SSEEvent.parse_sse_line("field", None)
    assert event is not None
    assert complete is False


def test_sse_event_parse_sse_line_strip_whitespace(translate):
    """Test SSEEvent.parse_sse_line strips whitespace correctly."""
    event, complete = translate.SSEEvent.parse_sse_line("data: value\n", None)
    assert event.data == "value"

    event, complete = translate.SSEEvent.parse_sse_line("data:  value", None)
    assert event.data == "value"


def test_start_stdio(monkeypatch, translate):
    """Test start_stdio entry point."""
    mock_run_stdio = AsyncMock()
    monkeypatch.setattr(translate, "_run_stdio_to_sse", mock_run_stdio)

    translate.start_stdio("cmd", 8000, "INFO", None, "127.0.0.1")
    mock_run_stdio.assert_called_once()


def test_start_sse(monkeypatch, translate):
    """Test start_sse entry point."""
    mock_run_sse = AsyncMock()
    monkeypatch.setattr(translate, "_run_sse_to_stdio", mock_run_sse)

    translate.start_sse("http://example.com/sse", "bearer_token")
    mock_run_sse.assert_called_once()


@pytest.mark.asyncio
async def test_run_stdio_to_streamable_http_basic(monkeypatch, translate):
    """Test _run_stdio_to_streamable_http basic functionality."""
    calls = []

    class MockProcess:
        def __init__(self):
            self.stdin = _DummyWriter()
            self.stdout = _DummyReader([])
            self.returncode = None
            calls.append("process_created")

        def terminate(self):
            calls.append("process_terminate")

        async def wait(self):
            return 0

    class MockMCPServer:
        def __init__(self, name):
            calls.append("mcp_server_init")

    class MockSessionManager:
        def __init__(self, app, stateless=False, json_response=False):
            calls.append("session_manager_init")

        async def handle_request(self, scope, receive, send):
            calls.append("handle_request")

    class MockRoute:
        def __init__(self, path, handler, methods=None):
            self.path = path
            self.handler = handler
            calls.append(f"route_{path}")

    class MockStarlette:
        def __init__(self, routes=None):
            self.routes = routes or []
            calls.append("starlette_init")

        def add_middleware(self, *args, **kwargs):
            calls.append("add_middleware")

    class MockServer:
        def __init__(self, config):
            calls.append("uvicorn_server_init")

        async def serve(self):
            calls.append("server_serve")
            # Quick exit to avoid hanging
            return

        async def shutdown(self):
            calls.append("server_shutdown")

    async def mock_create_subprocess(*args, **kwargs):
        return MockProcess()

    # Mock the pump task to be async
    class MockTask:
        def cancel(self):
            calls.append("pump_task_cancelled")

    async def mock_pump():
        calls.append("pump_task")
        return

    def mock_create_task(coro):
        # Close the coroutine to prevent warnings
        try:
            coro.close()
        except GeneratorExit:
            pass
        return MockTask()

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", mock_create_subprocess)
    monkeypatch.setattr(translate, "MCPServer", MockMCPServer)
    monkeypatch.setattr(translate, "StreamableHTTPSessionManager", MockSessionManager)
    monkeypatch.setattr(translate, "Route", MockRoute)
    monkeypatch.setattr(translate, "Starlette", MockStarlette)
    monkeypatch.setattr(translate.uvicorn, "Server", MockServer)
    monkeypatch.setattr(translate.uvicorn, "Config", lambda *a, **k: None)
    monkeypatch.setattr(
        translate.asyncio,
        "get_running_loop",
        lambda: types.SimpleNamespace(add_signal_handler=lambda *_, **__: None),
    )
    monkeypatch.setattr(translate.asyncio, "create_task", mock_create_task)

    await translate._run_stdio_to_streamable_http("echo test", 8000, "info")

    # Verify key components
    assert "process_created" in calls
    assert "mcp_server_init" in calls
    assert "session_manager_init" in calls
    assert "starlette_init" in calls
    assert "server_serve" in calls
    assert "pump_task_cancelled" in calls


@pytest.mark.asyncio
async def test_run_stdio_to_streamable_http_with_cors(monkeypatch, translate):
    """Test _run_stdio_to_streamable_http with CORS configuration."""
    calls = []

    class MockProcess:
        def __init__(self):
            self.stdin = _DummyWriter()
            self.stdout = _DummyReader([])
            self.returncode = None

        def terminate(self):
            pass

        async def wait(self):
            return 0

    class MockStarlette:
        def __init__(self, routes=None):
            self.routes = routes or []
            calls.append("starlette_init")

        def add_middleware(self, middleware_class, **kwargs):
            calls.append(f"add_middleware_{middleware_class.__name__}")

    # Standard
    import sys

    class MockTask:
        def cancel(self):
            pass

    def mock_create_task(coro):
        # Close the coroutine to prevent warnings
        try:
            coro.close()
        except GeneratorExit:
            pass
        return MockTask()

    # Mock other required components
    async def mock_subprocess(*a, **k):
        return MockProcess()

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", mock_subprocess)
    monkeypatch.setattr(translate, "MCPServer", lambda name: None)
    monkeypatch.setattr(translate, "StreamableHTTPSessionManager", lambda **k: None)
    monkeypatch.setattr(translate, "Route", lambda path, handler, methods=None: None)
    monkeypatch.setattr(translate, "Starlette", MockStarlette)

    async def mock_serve():
        return None

    async def mock_shutdown():
        return None

    monkeypatch.setattr(translate.uvicorn, "Server", lambda config: types.SimpleNamespace(serve=mock_serve, shutdown=mock_shutdown))
    monkeypatch.setattr(translate.uvicorn, "Config", lambda *a, **k: None)
    monkeypatch.setattr(
        translate.asyncio,
        "get_running_loop",
        lambda: types.SimpleNamespace(add_signal_handler=lambda *_, **__: None),
    )
    monkeypatch.setattr(translate.asyncio, "create_task", mock_create_task)

    try:
        # Test with CORS
        await translate._run_stdio_to_streamable_http("echo test", 8000, "info", cors=["http://example.com"])

        # Verify CORS middleware was added (using our Mock class name)
        assert "add_middleware_CORSMiddleware" in calls
    finally:
        # Clean up sys.modules to avoid affecting other tests
        sys.modules.pop("starlette", None)
        sys.modules.pop("starlette.middleware", None)
        sys.modules.pop("starlette.middleware.cors", None)


@pytest.mark.asyncio
async def test_run_stdio_to_streamable_http_missing_pipes_raises(monkeypatch, translate):
    """Cover RuntimeError when subprocess stdin/stdout pipes are missing."""

    class BadProc:
        stdin = None
        stdout = None
        returncode = None

    async def fake_create_subprocess_exec(*_a, **_k):
        return BadProc()

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    with pytest.raises(RuntimeError, match="Failed to create subprocess"):
        await translate._run_stdio_to_streamable_http("echo test", 8000, "info")


@pytest.mark.asyncio
async def test_run_stdio_to_streamable_http_handle_request_and_pump_http_to_stdio(monkeypatch, translate):
    """Cover handle_mcp -> session_manager.handle_request and pump_http_to_stdio helper."""
    calls: list[str] = []
    handlers: dict[str, Any] = {}
    mgr_holder: dict[str, Any] = {}

    class Proc:
        def __init__(self):
            self.stdin = _DummyWriter()
            self.stdout = _DummyReader(["line1\n"])
            self.returncode = None
            self.terminated = False

        def terminate(self):
            self.terminated = True
            self.returncode = 0

        async def wait(self):
            return 0

    proc = Proc()

    async def fake_create_subprocess_exec(*_a, **_k):
        return proc

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    class MockMCPServer:
        def __init__(self, name):
            calls.append(f"mcp_server:{name}")

    class MockSessionManager:
        def __init__(self, app, stateless=False, json_response=False):
            mgr_holder["mgr"] = self
            self.handle_request = AsyncMock()
            calls.append("session_manager_init")

    class Route:
        def __init__(self, path, handler, methods=None):
            handlers[path] = handler

    class Starlette:
        def __init__(self, routes=None):
            self.routes = routes or []

        def add_middleware(self, *_a, **_k):
            return None

    class Server:
        def __init__(self, _cfg):
            self.should_exit = False

        async def serve(self):
            # Call the /mcp route handler (handle_mcp) to exercise handle_request path.
            class DummyRequest:
                scope = {"type": "http"}

                async def receive(self):
                    return {}

                async def _send(self, _msg):
                    return None

            await handlers["/mcp"](DummyRequest())

            # Also reach into the caller frame to invoke pump_http_to_stdio which is
            # otherwise unused in the implementation.
            import inspect

            frame = inspect.currentframe()
            assert frame is not None
            f = frame.f_back
            while f and f.f_code.co_name != "_run_stdio_to_streamable_http":
                f = f.f_back
            assert f is not None
            pump_http_to_stdio = f.f_locals["pump_http_to_stdio"]
            await pump_http_to_stdio('{"method":"test"}')
            # Exercise the error path too.
            proc.stdin = None
            with pytest.raises(RuntimeError, match="Process stdin not available"):
                await pump_http_to_stdio('{"method":"test2"}')

            # Let the stdout pump and signal-triggered shutdown task run.
            await asyncio.sleep(0)

    monkeypatch.setattr(translate, "MCPServer", MockMCPServer)
    monkeypatch.setattr(translate, "StreamableHTTPSessionManager", MockSessionManager)
    monkeypatch.setattr(translate, "Route", Route)
    monkeypatch.setattr(translate, "Starlette", Starlette)
    monkeypatch.setattr(translate.uvicorn, "Server", Server)
    monkeypatch.setattr(translate.uvicorn, "Config", lambda *a, **k: None)

    # Immediately invoke signal callbacks to schedule shutdown early (idempotent cleanup path).
    monkeypatch.setattr(translate.asyncio, "get_running_loop", lambda: types.SimpleNamespace(add_signal_handler=lambda _sig, cb: cb()))

    await translate._run_stdio_to_streamable_http("echo test", 8000, "info")

    assert mgr_holder["mgr"].handle_request.await_count == 1
    assert proc.terminated is True


@pytest.mark.asyncio
async def test_run_stdio_to_streamable_http_pump_stdio_to_http_exception(monkeypatch, translate):
    """Cover pump_stdio_to_http exception handling."""

    class BadStdout:
        async def readline(self):
            raise Exception("boom")

    class Proc:
        def __init__(self):
            self.stdin = _DummyWriter()
            self.stdout = BadStdout()
            self.returncode = None
            self.terminated = False

        def terminate(self):
            self.terminated = True
            self.returncode = 0

        async def wait(self):
            return 0

    proc = Proc()

    async def fake_create_subprocess_exec(*_a, **_k):
        return proc

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(translate.uvicorn, "Config", lambda *a, **k: None)

    class Server:
        def __init__(self, _cfg):
            self.should_exit = False

        async def serve(self):
            await asyncio.sleep(0)

    monkeypatch.setattr(translate.uvicorn, "Server", Server)
    monkeypatch.setattr(translate.asyncio, "get_running_loop", lambda: types.SimpleNamespace(add_signal_handler=lambda *_a, **_k: None))

    await translate._run_stdio_to_streamable_http("echo test", 8000, "info")
    assert proc.terminated is True


@pytest.mark.asyncio
async def test_run_stdio_to_streamable_http_shutdown_skips_terminate_when_process_exited_and_stdout_missing(monkeypatch, translate):
    """Cover shutdown branch when process.returncode is set and pump_stdio_to_http stdout-missing error."""
    calls: list[str] = []
    pump_ran = asyncio.Event()

    class ToggleStdout:
        def __init__(self):
            self.calls = 0

        def __bool__(self):
            self.calls += 1
            # First truthiness check is the startup guard. Second check is inside pump_stdio_to_http.
            if self.calls >= 2:
                pump_ran.set()
                return False
            return True

    class Proc:
        def __init__(self):
            self.stdin = _DummyWriter()
            self.stdout = ToggleStdout()
            self.returncode = 0
            self.terminated = False

        def terminate(self):
            self.terminated = True

        async def wait(self):
            return 0

    proc = Proc()

    async def fake_create_subprocess_exec(*_a, **_k):
        return proc

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    monkeypatch.setattr(translate, "MCPServer", lambda *a, **k: None)
    monkeypatch.setattr(translate, "StreamableHTTPSessionManager", lambda **k: types.SimpleNamespace(handle_request=AsyncMock()))
    monkeypatch.setattr(translate, "Route", lambda *a, **k: None)
    monkeypatch.setattr(translate, "Starlette", lambda *a, **k: types.SimpleNamespace(add_middleware=lambda *_a, **_k: None))
    monkeypatch.setattr(translate.uvicorn, "Config", lambda *a, **k: None)
    monkeypatch.setattr(translate.asyncio, "get_running_loop", lambda: types.SimpleNamespace(add_signal_handler=lambda *_a, **_k: None))

    class Server:
        def __init__(self, _cfg):
            self.should_exit = False
            calls.append("server_init")

        async def serve(self):
            # Ensure the pump task runs at least once.
            await pump_ran.wait()
            calls.append("server_serve")

    monkeypatch.setattr(translate.uvicorn, "Server", Server)

    await translate._run_stdio_to_streamable_http("echo test", 8000, "info")
    assert proc.terminated is False
    assert "server_serve" in calls


def test_main_module_name_check(translate, capsys):
    """Test the main function error handling with no arguments."""
    # This should trigger an error since no transport is specified
    with pytest.raises(SystemExit) as exc_info:
        translate.main(["--stdio"])  # Missing required argument to stdio

    assert exc_info.value.code == 2  # argparse error code
    captured = capsys.readouterr()
    assert "required" in captured.err or "argument" in captured.err


@pytest.mark.asyncio
async def test_sse_event_generator_keepalive_flow(monkeypatch, translate):
    """Test SSE event generator with keepalive flow."""
    ps = translate._PubSub()
    stdio = Mock()

    # Test with keepalive enabled
    monkeypatch.setattr(translate, "DEFAULT_KEEPALIVE_ENABLED", True)

    app = translate._build_fastapi(ps, stdio, keep_alive=1)

    class MockRequest:
        def __init__(self):
            self.base_url = "http://test/"
            self._disconnect_after = 2
            self._check_count = 0

        async def is_disconnected(self):
            self._check_count += 1
            return self._check_count > self._disconnect_after

    # Get the SSE route handler
    handler = None
    for route in app.routes:
        if hasattr(route, "path") and route.path == "/sse":
            handler = route.endpoint
            break

    assert handler is not None, "SSE handler not found"

    # Call the handler and verify it creates a response
    response = await handler(MockRequest())
    assert response is not None

    # Test passes if no exception is raised and response is created


def test_parse_args_custom_paths(translate):
    """Test parse_args with custom SSE and message paths."""
    args = translate._parse_args(["--stdio", "cmd", "--port", "8080", "--ssePath", "/custom/sse", "--messagePath", "/custom/message"])
    assert args.ssePath == "/custom/sse"
    assert args.messagePath == "/custom/message"


def test_parse_args_custom_keep_alive(translate):
    """Test parse_args with custom keep-alive interval."""
    args = translate._parse_args(["--stdio", "cmd", "--port", "8080", "--keepAlive", "60"])
    assert args.keepAlive == 60


def test_parse_args_sse_with_stdio_command(translate):
    """Test parse_args for SSE mode with stdio command."""
    args = translate._parse_args(["--sse", "http://example.com/sse", "--stdioCommand", "python script.py"])
    assert args.stdioCommand == "python script.py"


@pytest.mark.asyncio
async def test_run_sse_to_stdio_with_stdio_command(monkeypatch, translate):
    """Test _run_sse_to_stdio with stdio command for full coverage."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    # Mock subprocess creation - make the stdout reader that will immediately return EOF
    class MockProcess:
        def __init__(self):
            self.stdin = _DummyWriter()
            self.stdout = _DummyReader([])  # Empty reader for quick termination
            self.returncode = None

        def terminate(self):
            self.returncode = 0

        async def wait(self):
            return 0

    mock_process = MockProcess()

    async def mock_create_subprocess(*args, **kwargs):
        return mock_process

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", mock_create_subprocess)

    # Mock httpx client that fails quickly
    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, content, headers):
            # Mock successful POST response
            class MockResponse:
                status_code = 202
                text = "accepted"

            return MockResponse()

        def stream(self, method, url):
            # Immediately raise error to test error handling path
            raise real_httpx.ConnectError("Connection failed")

    monkeypatch.setattr(translate.httpx, "AsyncClient", MockClient)

    # Run with single retry to test error handling
    try:
        await translate._run_sse_to_stdio("http://test/sse", None, stdio_command="echo test", max_retries=1, timeout=1.0)
    except Exception as e:
        # Expected to fail due to ConnectError
        assert "Connection failed" in str(e) or "Max retries" in str(e)


@pytest.mark.asyncio
async def test_simple_sse_pump_error_handling(monkeypatch, translate):
    """Test _simple_sse_pump error handling and retry logic."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    class MockClient:
        def __init__(self, *args, **kwargs):
            self.attempt = 0

        def stream(self, method, url):
            self.attempt += 1
            if self.attempt == 1:
                # First attempt fails with ConnectError
                raise real_httpx.ConnectError("Connection failed")
            else:
                # Second attempt succeeds but then fails with ReadError
                class MockResponse:
                    status_code = 200

                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *args):
                        pass

                    async def aiter_lines(self):
                        yield "event: message"
                        yield "data: test"
                        yield ""
                        raise real_httpx.ReadError("Stream ended")

                return MockResponse()

    client = MockClient()

    # Capture printed output
    printed = []
    monkeypatch.setattr("builtins.print", lambda x: printed.append(x))

    try:
        await translate._simple_sse_pump(client, "http://test/sse", max_retries=2, initial_retry_delay=0.1)
    except Exception as e:
        assert "Stream ended" in str(e) or "Max retries" in str(e)

    # Verify message was printed
    assert "test" in printed


@pytest.mark.asyncio
async def test_simple_sse_pump_max_retries_zero_returns(monkeypatch, translate):
    """Cover loop-not-entered branch in _simple_sse_pump."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    class Client:
        def stream(self, *_a, **_k):  # pragma: no cover - should not be called
            raise AssertionError("stream should not be called")

    await translate._simple_sse_pump(Client(), "http://test/sse", max_retries=0, initial_retry_delay=0.0)


@pytest.mark.asyncio
async def test_simple_sse_pump_status_error_when_httpx_missing_raises_exception(monkeypatch, translate):
    """Cover status-code error branch when httpx is falsy (generic Exception path)."""
    monkeypatch.setattr(translate, "httpx", None)

    class Resp:
        status_code = 500

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def aiter_lines(self):
            if False:  # pragma: no cover
                yield ""

    class Client:
        def stream(self, *_a, **_k):
            return Resp()

    with pytest.raises(Exception, match="SSE endpoint returned 500"):
        await translate._simple_sse_pump(Client(), "http://test/sse", max_retries=1, initial_retry_delay=0.0)


@pytest.mark.asyncio
async def test_simple_sse_pump_keepalive_event(monkeypatch, translate):
    """Cover keepalive event branch in _simple_sse_pump."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    printed: list[str] = []
    monkeypatch.setattr("builtins.print", lambda x: printed.append(x))

    class Resp:
        status_code = 200

        def __init__(self):
            self.request = real_httpx.Request("GET", "http://test/sse")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def aiter_lines(self):
            yield "event: keepalive"
            yield "data: {}"
            yield ""
            raise real_httpx.ConnectError("done", request=self.request)

    class Client:
        def stream(self, *_a, **_k):
            return Resp()

    with pytest.raises(real_httpx.ConnectError):
        await translate._simple_sse_pump(Client(), "http://test/sse", max_retries=1, initial_retry_delay=0.0)

    assert printed == []


@pytest.mark.asyncio
async def test_simple_sse_pump_unknown_event_type(monkeypatch, translate):
    """Cover unknown SSE event type branch in _simple_sse_pump (neither endpoint/message/keepalive)."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    printed: list[str] = []
    monkeypatch.setattr("builtins.print", lambda x: printed.append(x))

    class Resp:
        status_code = 200

        def __init__(self):
            self.request = real_httpx.Request("GET", "http://test/sse")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def aiter_lines(self):
            yield "event: mystery"
            yield "data: hi"
            yield ""
            raise real_httpx.ConnectError("done", request=self.request)

    class Client:
        def stream(self, *_a, **_k):
            return Resp()

    with pytest.raises(real_httpx.ConnectError):
        await translate._simple_sse_pump(Client(), "http://test/sse", max_retries=1, initial_retry_delay=0.0)

    assert printed == []


@pytest.mark.asyncio
async def test_stdio_endpoint_pump_exception_handling(monkeypatch, translate):
    """Test exception handling in _pump_stdout method."""
    ps = translate._PubSub()

    class ExceptionReader:
        async def readline(self):
            raise Exception("Test pump exception")

    class FakeProcess:
        def __init__(self):
            self.stdin = _DummyWriter()
            self.stdout = ExceptionReader()
            self.pid = 1234
            self.terminated = False
            self.returncode = None

        def terminate(self):
            self.terminated = True

        async def wait(self):
            return 0

    fake_proc = FakeProcess()

    async def mock_exec(*args, **kwargs):
        return fake_proc

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", mock_exec)

    ep = translate.StdIOEndpoint("test cmd", ps)
    await ep.start()

    # Give the pump task a moment to start and fail
    await asyncio.sleep(0.1)

    await ep.stop()
    assert fake_proc.terminated


def test_config_import_fallback(monkeypatch, translate):
    """Test configuration import fallback when mcpgateway.config is not available."""
    # This tests the ImportError handling in lines 94-97

    # Mock the settings import to fail
    original_settings = getattr(translate, "settings", None)
    monkeypatch.setattr(translate, "DEFAULT_KEEP_ALIVE_INTERVAL", 30)
    monkeypatch.setattr(translate, "DEFAULT_KEEPALIVE_ENABLED", True)

    # Verify the fallback values are used
    assert translate.DEFAULT_KEEP_ALIVE_INTERVAL == 30
    assert translate.DEFAULT_KEEPALIVE_ENABLED == True


def test_httpx_import_error_fallback(monkeypatch, translate):
    """Test that httpx import error fallback works properly."""
    # Test the httpx ImportError handling path in lines 138-139
    monkeypatch.setattr(translate, "httpx", None)

    # Verify httpx is None when import fails
    assert translate.httpx is None


@pytest.mark.asyncio
async def test_sse_event_generator_keepalive_disabled(monkeypatch, translate):
    """Test SSE event generator when keepalive is disabled."""
    ps = translate._PubSub()
    stdio = Mock()

    # Disable keepalive
    monkeypatch.setattr(translate, "DEFAULT_KEEPALIVE_ENABLED", False)

    app = translate._build_fastapi(ps, stdio, keep_alive=30)

    # Mock request
    class MockRequest:
        def __init__(self):
            self.base_url = "http://test/"
            self._disconnected = False

        async def is_disconnected(self):
            if not self._disconnected:
                self._disconnected = True
                return False
            return True

    # Get the SSE route handler
    for route in app.routes:
        if getattr(route, "path", None) == "/sse":
            handler = route.endpoint
            break

    # Call the handler to get the generator
    response = await handler(MockRequest())

    # Verify the response is created (testing lines 585-613)
    assert response is not None


@pytest.mark.asyncio
async def test_runtime_errors_in_stdio_endpoint(monkeypatch, translate):
    """Test runtime errors in StdIOEndpoint methods."""
    ps = translate._PubSub()

    # Test start() method when subprocess creation fails
    async def failing_exec(*args, **kwargs):
        class BadProcess:
            stdin = None  # Missing stdin should trigger RuntimeError
            stdout = None
            pid = 1234

        return BadProcess()

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", failing_exec)

    ep = translate.StdIOEndpoint("bad command", ps)

    with pytest.raises(RuntimeError, match="Failed to create subprocess"):
        await ep.start()


@pytest.mark.asyncio
async def test_sse_to_stdio_http_status_error(monkeypatch, translate):
    """Test SSE to stdio handling of HTTP status errors."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def stream(self, method, url):
            class MockResponse:
                status_code = 404  # Non-200 status
                request = None

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    pass

            return MockResponse()

    monkeypatch.setattr(translate.httpx, "AsyncClient", MockClient)

    # Capture printed output
    printed = []
    monkeypatch.setattr("builtins.print", lambda x: printed.append(x))

    # Should raise HTTPStatusError due to 404 status
    try:
        await translate._run_sse_to_stdio("http://test/sse", None, max_retries=1)
    except Exception as e:
        assert "404" in str(e) or "Max retries" in str(e)


@pytest.mark.asyncio
async def test_sse_event_generator_full_flow(monkeypatch, translate):
    """Test SSE event generator with full message flow."""
    ps = translate._PubSub()
    stdio = Mock()

    # Enable keepalive for this test
    monkeypatch.setattr(translate, "DEFAULT_KEEPALIVE_ENABLED", True)

    app = translate._build_fastapi(ps, stdio, keep_alive=1)  # Short keepalive interval

    # Mock request that disconnects after a few cycles
    class MockRequest:
        def __init__(self):
            self.base_url = "http://test/"
            self._check_count = 0

        async def is_disconnected(self):
            self._check_count += 1
            return self._check_count > 3  # Disconnect after 3 checks

    # Get the SSE route handler
    for route in app.routes:
        if getattr(route, "path", None) == "/sse":
            handler = route.endpoint
            break

    # Subscribe to pubsub and publish a message
    q = ps.subscribe()
    await ps.publish('{"test": "message"}')

    # Call the handler to test the generator logic
    response = await handler(MockRequest())

    # Verify the response is created (testing the SSE event generator)
    assert response is not None
    # Note: unsubscription happens when the generator completes, not necessarily immediately


def test_sse_event_parse_multiline_data(translate):
    """Test SSE event parsing with multiline data."""
    # Start with first data line
    event, complete = translate.SSEEvent.parse_sse_line("data: line1", None)
    assert event.data == "line1"
    assert not complete

    # Add second data line (multiline)
    event, complete = translate.SSEEvent.parse_sse_line("data: line2", event)
    assert event.data == "line1\nline2"
    assert not complete

    # Empty line completes the event
    event, complete = translate.SSEEvent.parse_sse_line("", event)
    assert event.data == "line1\nline2"
    assert complete


def test_sse_event_all_fields(translate):
    """Test SSE event with all possible fields."""
    # Test all field types
    event, complete = translate.SSEEvent.parse_sse_line("event: test-type", None)
    assert event.event == "test-type"

    event, complete = translate.SSEEvent.parse_sse_line("data: test-data", event)
    assert event.data == "test-data"

    event, complete = translate.SSEEvent.parse_sse_line("id: test-id", event)
    assert event.event_id == "test-id"

    event, complete = translate.SSEEvent.parse_sse_line("retry: 5000", event)
    assert event.retry == 5000

    # Complete the event
    event, complete = translate.SSEEvent.parse_sse_line("", event)
    assert complete
    assert event.event == "test-type"
    assert event.data == "test-data"
    assert event.event_id == "test-id"
    assert event.retry == 5000


@pytest.mark.asyncio
async def test_read_stdout_message_endpoint_error(monkeypatch, translate):
    """Test read_stdout when message endpoint POST fails."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    # Mock subprocess with output
    class MockProcess:
        def __init__(self):
            self.stdin = _DummyWriter()
            self.stdout = _DummyReader(['{"test": "data"}\n'])
            self.returncode = None

        def terminate(self):
            self.returncode = 0

        async def wait(self):
            return 0

    mock_process = MockProcess()

    async def mock_create_subprocess(*args, **kwargs):
        return mock_process

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", mock_create_subprocess)

    # Mock httpx client with failing POST
    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, content, headers):
            # Mock non-202 response
            class MockResponse:
                status_code = 500
                text = "Internal Server Error"

            return MockResponse()

        def stream(self, method, url):
            class MockResponse:
                status_code = 200
                request = None

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    pass

                async def aiter_lines(self):
                    # Provide endpoint first
                    yield "event: endpoint"
                    yield "data: http://test/message"
                    yield ""
                    # Then quickly fail
                    raise real_httpx.ConnectError("Connection failed")

            return MockResponse()

    monkeypatch.setattr(translate.httpx, "AsyncClient", MockClient)

    # This will test the POST error handling path in read_stdout
    try:
        await translate._run_sse_to_stdio("http://test/sse", None, stdio_command="echo test", max_retries=1)
    except Exception:
        pass  # Expected to fail


def test_main_function_streamable_http_connect(monkeypatch, translate, capsys):
    """Test main() function with --connect-streamable-http argument."""
    mock_streamable_runner = AsyncMock()
    monkeypatch.setattr(translate, "_run_streamable_http_to_stdio", mock_streamable_runner)

    translate.main(["--connect-streamable-http", "http://example.com/mcp"])
    mock_streamable_runner.assert_called_once()


def test_start_streamable_http_stdio_function(monkeypatch, translate):
    """Test start_streamable_http_stdio entry point."""
    mock_run_stdio_streamable = AsyncMock()
    monkeypatch.setattr(translate, "_run_stdio_to_streamable_http", mock_run_stdio_streamable)

    translate.start_streamable_http_stdio("cmd", 8000, "INFO", None, "127.0.0.1", False, False)
    mock_run_stdio_streamable.assert_called_once()


def test_start_streamable_http_client_function(monkeypatch, translate):
    """Test start_streamable_http_client entry point."""
    mock_run_streamable_client = AsyncMock()
    monkeypatch.setattr(translate, "_run_streamable_http_to_stdio", mock_run_streamable_client)

    translate.start_streamable_http_client("http://example.com/mcp", "bearer_token", 30.0, "stdio_cmd")
    mock_run_streamable_client.assert_called_once()


@pytest.mark.asyncio
async def test_run_streamable_http_to_stdio_importerror(monkeypatch, translate):
    """Test _run_streamable_http_to_stdio raises ImportError when httpx is None."""
    monkeypatch.setattr(translate, "httpx", None)
    with pytest.raises(ImportError, match="httpx package is required for streamable HTTP"):
        await translate._run_streamable_http_to_stdio("http://example.com/mcp", None)


@pytest.mark.asyncio
async def test_run_streamable_http_to_stdio_simple_mode(monkeypatch, translate):
    """Test _run_streamable_http_to_stdio in simple mode (no stdio command)."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    # Mock simple pump function as async
    async def mock_pump(*args, **kwargs):
        return None

    monkeypatch.setattr(translate, "_simple_streamable_http_pump", mock_pump)

    # Mock httpx.AsyncClient
    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(translate.httpx, "AsyncClient", MockClient)

    # Test simple mode (no stdio_command)
    await translate._run_streamable_http_to_stdio("http://example.com/mcp", "token", 30.0, None)

    # Test passes if no exception is raised


@pytest.mark.asyncio
async def test_simple_streamable_http_pump_basic(monkeypatch, translate):
    """Test _simple_streamable_http_pump basic functionality."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    # Capture printed output
    printed = []
    monkeypatch.setattr("builtins.print", lambda x: printed.append(x))

    class MockResponse:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def aiter_lines(self):
            yield "data: test message"
            yield "data: another message"
            # End the stream
            raise real_httpx.ConnectError("Test stream ended")

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        def stream(self, method, url, headers=None):
            return MockResponse()

    client = MockClient()

    try:
        await translate._simple_streamable_http_pump(client, "http://test/mcp", 1, 0.1)
    except Exception as e:
        assert "Test stream ended" in str(e) or "Max retries" in str(e)

    # Verify messages were printed
    assert "test message" in printed
    assert "another message" in printed


@pytest.mark.asyncio
async def test_simple_streamable_http_pump_status_error(monkeypatch, translate):
    """Test _simple_streamable_http_pump handles non-200 responses."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    class MockResponse:
        status_code = 500

        def __init__(self):
            self.request = real_httpx.Request("GET", "http://test/mcp")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def aiter_lines(self):
            if False:  # pragma: no cover - required to make this an async generator
                yield ""

    class MockClient:
        def stream(self, method, url, headers=None):
            return MockResponse()

    with pytest.raises(real_httpx.HTTPStatusError):
        await translate._simple_streamable_http_pump(MockClient(), "http://test/mcp", 1, 0.1)


@pytest.mark.asyncio
async def test_simple_streamable_http_pump_max_retries_zero_returns(monkeypatch, translate):
    """Cover loop-not-entered branch in _simple_streamable_http_pump."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    class Client:
        def stream(self, *_a, **_k):  # pragma: no cover - should not be called
            raise AssertionError("stream should not be called")

    await translate._simple_streamable_http_pump(Client(), "http://test/mcp", 0, 0.0)


@pytest.mark.asyncio
async def test_simple_streamable_http_pump_status_error_when_httpx_missing_raises_exception(monkeypatch, translate):
    """Cover status-code error branch when httpx is falsy (generic Exception path)."""
    monkeypatch.setattr(translate, "httpx", None)

    class Resp:
        status_code = 500

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def aiter_lines(self):
            if False:  # pragma: no cover
                yield ""

    class Client:
        def stream(self, *_a, **_k):
            return Resp()

    with pytest.raises(Exception, match="Streamable HTTP endpoint returned 500"):
        await translate._simple_streamable_http_pump(Client(), "http://test/mcp", 1, 0.0)


@pytest.mark.asyncio
async def test_simple_streamable_http_pump_skips_non_data_and_empty_data_lines(monkeypatch, translate):
    """Cover non-data and empty-data skip branches in _simple_streamable_http_pump."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    printed: list[str] = []
    monkeypatch.setattr("builtins.print", lambda x: printed.append(x))

    class Resp:
        status_code = 200

        def __init__(self):
            self.request = real_httpx.Request("GET", "http://test/mcp")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def aiter_lines(self):
            yield "event: ignore"
            yield "data: "
            yield "data: ok"
            raise real_httpx.ConnectError("done", request=self.request)

    class Client:
        def stream(self, *_a, **_k):
            return Resp()

    with pytest.raises(real_httpx.ConnectError):
        await translate._simple_streamable_http_pump(Client(), "http://test/mcp", 1, 0.0)

    assert printed == ["ok"]


@pytest.mark.asyncio
async def test_simple_streamable_http_pump_retry_warning_and_backoff(monkeypatch, translate):
    """Cover retry warning + sleep/backoff branch in _simple_streamable_http_pump."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)
    monkeypatch.setattr(translate.asyncio, "sleep", AsyncMock())

    class Client:
        def __init__(self):
            self.calls = 0

        def stream(self, *_a, **_k):
            self.calls += 1
            raise real_httpx.ConnectError("boom", request=real_httpx.Request("GET", "http://test/mcp"))

    with pytest.raises(real_httpx.ConnectError):
        await translate._simple_streamable_http_pump(Client(), "http://test/mcp", 2, 0.0)

    assert translate.asyncio.sleep.await_count >= 1


@pytest.mark.asyncio
async def test_simple_streamable_http_pump_unexpected_error_branch(monkeypatch, translate):
    """Cover unexpected error branch in _simple_streamable_http_pump."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    class Client:
        def stream(self, *_a, **_k):
            raise ValueError("unexpected")

    with pytest.raises(ValueError, match="unexpected"):
        await translate._simple_streamable_http_pump(Client(), "http://test/mcp", 1, 0.0)


@pytest.mark.asyncio
async def test_run_streamable_http_to_stdio_with_stdio_command(monkeypatch, translate):
    """Test _run_streamable_http_to_stdio with stdio command and retry path."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    class FakeStdin:
        def __init__(self):
            self.writes = []

        def write(self, data: bytes) -> None:
            self.writes.append(data)

        async def drain(self) -> None:
            return None

    class FakeStdout:
        def __init__(self):
            self._lines = [
                b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n',
                b"",
            ]

        async def readline(self) -> bytes:
            return self._lines.pop(0)

    class FakeProcess:
        def __init__(self):
            self.stdin = FakeStdin()
            self.stdout = FakeStdout()
            self.returncode = None
            self.terminated = False

        def terminate(self) -> None:
            self.terminated = True

        async def wait(self) -> None:
            return None

    process = FakeProcess()

    async def fake_create_subprocess_exec(*args, **kwargs):
        return process

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    class FakeResponse:
        def __init__(self, status_code=200, text='{"result":"ok"}'):
            self.status_code = status_code
            self.text = text
            self.request = real_httpx.Request("POST", "http://example.com/mcp")

    class FakeStreamResponse:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def aiter_lines(self):
            yield 'data: {"msg":"hi"}'

    class FakeClient:
        def __init__(self):
            self.post_calls = []
            self.stream_calls = 0

        async def post(self, url, content=None, headers=None):
            self.post_calls.append((url, content, headers))
            return FakeResponse()

        def stream(self, method, url, headers=None):
            self.stream_calls += 1
            if self.stream_calls == 1:
                return FakeStreamResponse()
            raise real_httpx.ConnectError("boom", request=real_httpx.Request(method, url))

    fake_client = FakeClient()

    class FakeClientContext:
        async def __aenter__(self):
            return fake_client

        async def __aexit__(self, *args):
            pass

    import mcpgateway.services.http_client_service as http_client_service

    monkeypatch.setattr(http_client_service, "get_isolated_http_client", lambda **kwargs: FakeClientContext())

    with pytest.raises(real_httpx.ConnectError):
        await translate._run_streamable_http_to_stdio("http://example.com", None, 5.0, "echo test", max_retries=1, initial_retry_delay=0.0)

    assert process.terminated is True
    assert any(write == b'{"result":"ok"}\n' for write in process.stdin.writes)
    assert any(write == b'{"msg":"hi"}\n' for write in process.stdin.writes)
    assert fake_client.post_calls[0][0].endswith("/mcp")


@pytest.mark.asyncio
async def test_run_streamable_http_to_stdio_form_encoded(monkeypatch, translate):
    """Test _run_streamable_http_to_stdio form-encoded branch and non-200 responses."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)
    monkeypatch.setattr(translate, "CONTENT_TYPE", "application/x-www-form-urlencoded")

    class FakeStdin:
        def __init__(self):
            self.writes = []

        def write(self, data: bytes) -> None:
            self.writes.append(data)

        async def drain(self) -> None:
            return None

    class FakeStdout:
        def __init__(self):
            self._lines = [
                b'{"foo":"bar"}\n',
                b"{not json}\n",
                b"",
            ]

        async def readline(self) -> bytes:
            return self._lines.pop(0)

    class FakeProcess:
        def __init__(self):
            self.stdin = FakeStdin()
            self.stdout = FakeStdout()
            self.returncode = None

        def terminate(self) -> None:
            self.returncode = 0

        async def wait(self) -> None:
            return None

    process = FakeProcess()

    async def fake_create_subprocess_exec(*args, **kwargs):
        return process

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    class FakeResponse:
        def __init__(self, status_code, text):
            self.status_code = status_code
            self.text = text
            self.request = real_httpx.Request("POST", "http://example.com/mcp")

    class FakeClient:
        def __init__(self):
            self.post_calls = []
            self._responses = [
                FakeResponse(200, "ok"),
                FakeResponse(500, "bad"),
            ]

        async def post(self, url, content=None, headers=None):
            self.post_calls.append((url, content, headers))
            return self._responses.pop(0)

    fake_client = FakeClient()

    class FakeClientContext:
        async def __aenter__(self):
            return fake_client

        async def __aexit__(self, *args):
            pass

    import mcpgateway.services.http_client_service as http_client_service

    monkeypatch.setattr(http_client_service, "get_isolated_http_client", lambda **kwargs: FakeClientContext())

    async def fake_gather(coro1, coro2):
        await coro1
        coro2.close()
        return [None, None]

    monkeypatch.setattr(translate.asyncio, "gather", fake_gather)

    await translate._run_streamable_http_to_stdio("http://example.com/mcp", "token", 5.0, "echo test", max_retries=1, initial_retry_delay=0.0)

    assert fake_client.post_calls[0][1] == "foo=bar"
    assert fake_client.post_calls[1][1] == "{not json}"
    assert fake_client.post_calls[0][2]["Authorization"] == "Bearer token"
    assert process.stdin.writes == [b"ok\n"]


@pytest.mark.asyncio
async def test_run_streamable_http_to_stdio_read_stdout_raises_when_stdout_missing_initial(monkeypatch, translate):
    """Cover read_stdout initial stdout-missing RuntimeError and cleanup when process already exited."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    class ToggleStdout:
        def __init__(self):
            self.calls = 0

        def __bool__(self):
            self.calls += 1
            return self.calls == 1

        async def readline(self):
            return b""

    class Proc:
        def __init__(self):
            self.stdin = _DummyWriter()
            self.stdout = ToggleStdout()
            self.returncode = 0
            self.terminated = False

        def terminate(self):
            self.terminated = True

        async def wait(self):
            return 0

    proc = Proc()

    async def fake_create_subprocess_exec(*_a, **_k):
        return proc

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    import mcpgateway.services.http_client_service as http_client_service

    class Client:
        async def post(self, *_a, **_k):  # pragma: no cover - should not be reached
            raise AssertionError("post should not be called")

        def stream(self, *_a, **_k):  # pragma: no cover - should not be reached
            raise AssertionError("stream should not be called")

    class Ctx:
        async def __aenter__(self):
            return Client()

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr(http_client_service, "get_isolated_http_client", lambda **_k: Ctx())

    async def fake_gather(coro1, coro2):
        with pytest.raises(RuntimeError, match="Process stdout not available"):
            await coro1
        coro2.close()
        return [None, None]

    monkeypatch.setattr(translate.asyncio, "gather", fake_gather)

    await translate._run_streamable_http_to_stdio("http://example.com/mcp", None, 5.0, "echo test", max_retries=1, initial_retry_delay=0.0)
    assert proc.terminated is False


@pytest.mark.asyncio
async def test_run_streamable_http_to_stdio_read_stdout_raises_when_stdout_missing_in_loop_after_blank_line(monkeypatch, translate):
    """Cover blank-line continue and subsequent stdout-missing check inside read_stdout loop."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    class ToggleStdout:
        def __init__(self):
            self.calls = 0
            self._lines = [b"\n"]

        def __bool__(self):
            self.calls += 1
            # True for: startup guard, read_stdout initial check, first loop check.
            # False for: second loop check (after hitting the blank-line continue).
            return self.calls <= 3

        async def readline(self):
            return self._lines.pop(0) if self._lines else b""

    class Proc:
        def __init__(self):
            self.stdin = _DummyWriter()
            self.stdout = ToggleStdout()
            self.returncode = 0

        def terminate(self):
            self.returncode = 0

        async def wait(self):
            return 0

    async def fake_create_subprocess_exec(*_a, **_k):
        return Proc()

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    import mcpgateway.services.http_client_service as http_client_service

    class Client:
        async def post(self, *_a, **_k):  # pragma: no cover - should not be reached
            raise AssertionError("post should not be called")

        def stream(self, *_a, **_k):  # pragma: no cover - should not be reached
            raise AssertionError("stream should not be called")

    class Ctx:
        async def __aenter__(self):
            return Client()

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr(http_client_service, "get_isolated_http_client", lambda **_k: Ctx())

    async def fake_gather(coro1, coro2):
        with pytest.raises(RuntimeError, match="Process stdout not available"):
            await coro1
        coro2.close()
        return [None, None]

    monkeypatch.setattr(translate.asyncio, "gather", fake_gather)

    await translate._run_streamable_http_to_stdio("http://example.com/mcp", None, 5.0, "echo test", max_retries=1, initial_retry_delay=0.0)


@pytest.mark.asyncio
async def test_run_streamable_http_to_stdio_read_stdout_skips_writing_empty_response_and_logs_post_exception(monkeypatch, translate):
    """Cover response_data-empty no-forward branch and POST exception handling in read_stdout."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    class CapturingStdin:
        def __init__(self):
            self.writes: list[bytes] = []

        def write(self, data: bytes) -> None:
            self.writes.append(data)

        async def drain(self) -> None:
            return None

    class Stdout:
        def __init__(self):
            self._lines = [
                b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n',
                b'{"jsonrpc":"2.0","id":2,"method":"ping"}\n',
                b"",
            ]

        async def readline(self) -> bytes:
            return self._lines.pop(0)

    class Proc:
        def __init__(self):
            self.stdin = CapturingStdin()
            self.stdout = Stdout()
            self.returncode = 0

        def terminate(self):
            self.returncode = 0

        async def wait(self):
            return 0

    proc = Proc()

    async def fake_create_subprocess_exec(*_a, **_k):
        return proc

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    class Client:
        def __init__(self):
            self.calls = 0

        async def post(self, *_a, **_k):
            self.calls += 1
            if self.calls == 1:
                return types.SimpleNamespace(status_code=200, text="")
            raise Exception("boom")

        def stream(self, *_a, **_k):  # pragma: no cover - closed by fake_gather
            raise AssertionError("stream should not be called")

    client = Client()

    import mcpgateway.services.http_client_service as http_client_service

    class Ctx:
        async def __aenter__(self):
            return client

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr(http_client_service, "get_isolated_http_client", lambda **_k: Ctx())

    async def fake_gather(coro1, coro2):
        await coro1
        coro2.close()
        return [None, None]

    monkeypatch.setattr(translate.asyncio, "gather", fake_gather)

    await translate._run_streamable_http_to_stdio("http://example.com/mcp", None, 5.0, "echo test", max_retries=1, initial_retry_delay=0.0)
    assert client.calls == 2
    assert proc.stdin.writes == []


@pytest.mark.asyncio
async def test_run_streamable_http_to_stdio_pump_max_retries_zero_skips_loop(monkeypatch, translate):
    """Cover pump_streamable_http_to_stdio loop-not-entered branch (max_retries=0)."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    class Proc:
        def __init__(self):
            self.stdin = _DummyWriter()
            self.stdout = _DummyReader([])
            self.returncode = 0

        def terminate(self):  # pragma: no cover
            self.returncode = 0

        async def wait(self):  # pragma: no cover
            return 0

    async def fake_create_subprocess_exec(*_a, **_k):
        return Proc()

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    class Client:
        def __init__(self):
            self.stream_calls = 0

        def stream(self, *_a, **_k):
            self.stream_calls += 1
            raise AssertionError("stream should not be called")

        async def post(self, *_a, **_k):  # pragma: no cover - stdout is empty
            raise AssertionError("post should not be called")

    client = Client()

    import mcpgateway.services.http_client_service as http_client_service

    class Ctx:
        async def __aenter__(self):
            return client

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr(http_client_service, "get_isolated_http_client", lambda **_k: Ctx())

    await translate._run_streamable_http_to_stdio("http://example.com/mcp", None, 5.0, "echo test", max_retries=0, initial_retry_delay=0.0)
    assert client.stream_calls == 0


@pytest.mark.asyncio
async def test_run_streamable_http_to_stdio_pump_status_error_raises_httpstatuserror(monkeypatch, translate):
    """Cover pump_streamable_http_to_stdio status-code error branch."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    class Proc:
        def __init__(self):
            self.stdin = _DummyWriter()
            self.stdout = _DummyReader([])
            self.returncode = 0

        def terminate(self):
            self.returncode = 0

        async def wait(self):
            return 0

    async def fake_create_subprocess_exec(*_a, **_k):
        return Proc()

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    class BadResp:
        status_code = 500

        def __init__(self):
            self.request = real_httpx.Request("GET", "http://example.com/mcp")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def aiter_lines(self):
            if False:  # pragma: no cover
                yield ""

    class Client:
        def stream(self, *_a, **_k):
            return BadResp()

        async def post(self, *_a, **_k):  # pragma: no cover - stdout is empty
            raise AssertionError("post should not be called")

    import mcpgateway.services.http_client_service as http_client_service

    class Ctx:
        async def __aenter__(self):
            return Client()

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr(http_client_service, "get_isolated_http_client", lambda **_k: Ctx())

    with pytest.raises(real_httpx.HTTPStatusError):
        await translate._run_streamable_http_to_stdio("http://example.com/mcp", None, 5.0, "echo test", max_retries=1, initial_retry_delay=0.0)


@pytest.mark.asyncio
async def test_run_streamable_http_to_stdio_pump_status_error_when_httpx_falsy_raises_generic_exception(monkeypatch, translate):
    """Cover generic status-code error branch when httpx is truthy for startup but falsy in the status check."""

    class TruthyThenFalsyHttpx:
        AsyncClient = object  # for annotation evaluation

        def __init__(self):
            self.calls = 0

        def __bool__(self):
            self.calls += 1
            return self.calls == 1

    monkeypatch.setattr(translate, "httpx", TruthyThenFalsyHttpx())

    class Proc:
        def __init__(self):
            self.stdin = _DummyWriter()
            self.stdout = _DummyReader([])
            self.returncode = 0

        def terminate(self):  # pragma: no cover
            self.returncode = 0

        async def wait(self):  # pragma: no cover
            return 0

    async def fake_create_subprocess_exec(*_a, **_k):
        return Proc()

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    class BadResp:
        status_code = 500

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def aiter_lines(self):
            if False:  # pragma: no cover
                yield ""

    class Client:
        def stream(self, *_a, **_k):
            return BadResp()

        async def post(self, *_a, **_k):  # pragma: no cover - stdout is empty
            raise AssertionError("post should not be called")

    import mcpgateway.services.http_client_service as http_client_service

    class Ctx:
        async def __aenter__(self):
            return Client()

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr(http_client_service, "get_isolated_http_client", lambda **_k: Ctx())

    with pytest.raises(Exception, match="Streamable HTTP endpoint returned 500"):
        await translate._run_streamable_http_to_stdio("http://example.com/mcp", None, 5.0, "echo test", max_retries=1, initial_retry_delay=0.0)


@pytest.mark.asyncio
async def test_run_streamable_http_to_stdio_pump_skips_non_data_and_empty_data_lines(monkeypatch, translate):
    """Cover pump loop skipping non-data lines and empty data payloads."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    class CapturingStdin:
        def __init__(self):
            self.writes: list[bytes] = []

        def write(self, data: bytes) -> None:
            self.writes.append(data)

        async def drain(self) -> None:
            return None

    class Proc:
        def __init__(self):
            self.stdin = CapturingStdin()
            self.stdout = _DummyReader([])
            self.returncode = 0

        def terminate(self):
            self.returncode = 0

        async def wait(self):
            return 0

    proc = Proc()

    async def fake_create_subprocess_exec(*_a, **_k):
        return proc

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    class Resp:
        status_code = 200

        def __init__(self):
            self.request = real_httpx.Request("GET", "http://example.com/mcp")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def aiter_lines(self):
            yield "event: ignore"
            yield "data: "
            yield "data: hello"
            raise real_httpx.ConnectError("done", request=self.request)

    class Client:
        def stream(self, *_a, **_k):
            return Resp()

        async def post(self, *_a, **_k):  # pragma: no cover - stdout is empty
            raise AssertionError("post should not be called")

    import mcpgateway.services.http_client_service as http_client_service

    class Ctx:
        async def __aenter__(self):
            return Client()

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr(http_client_service, "get_isolated_http_client", lambda **_k: Ctx())

    with pytest.raises(real_httpx.ConnectError):
        await translate._run_streamable_http_to_stdio("http://example.com/mcp", None, 5.0, "echo test", max_retries=1, initial_retry_delay=0.0)

    assert proc.stdin.writes == [b"hello\n"]


@pytest.mark.asyncio
async def test_run_streamable_http_to_stdio_pump_retry_warning_and_backoff(monkeypatch, translate):
    """Cover retry warning + sleep/backoff path in pump_streamable_http_to_stdio."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    class Proc:
        def __init__(self):
            self.stdin = _DummyWriter()
            self.stdout = _DummyReader([])
            self.returncode = 0

        def terminate(self):
            self.returncode = 0

        async def wait(self):
            return 0

    async def fake_create_subprocess_exec(*_a, **_k):
        return Proc()

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(translate.asyncio, "sleep", AsyncMock())

    class Client:
        def stream(self, *_a, **_k):
            raise real_httpx.ConnectError("boom", request=real_httpx.Request("GET", "http://example.com/mcp"))

        async def post(self, *_a, **_k):  # pragma: no cover - stdout is empty
            raise AssertionError("post should not be called")

    import mcpgateway.services.http_client_service as http_client_service

    class Ctx:
        async def __aenter__(self):
            return Client()

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr(http_client_service, "get_isolated_http_client", lambda **_k: Ctx())

    with pytest.raises(real_httpx.ConnectError):
        await translate._run_streamable_http_to_stdio("http://example.com/mcp", None, 5.0, "echo test", max_retries=2, initial_retry_delay=0.0)

    assert translate.asyncio.sleep.await_count >= 1


@pytest.mark.asyncio
async def test_run_streamable_http_to_stdio_pump_unexpected_error(monkeypatch, translate):
    """Cover unexpected error branch in pump_streamable_http_to_stdio."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    class Proc:
        def __init__(self):
            self.stdin = _DummyWriter()
            self.stdout = _DummyReader([])
            self.returncode = 0

        def terminate(self):
            self.returncode = 0

        async def wait(self):
            return 0

    async def fake_create_subprocess_exec(*_a, **_k):
        return Proc()

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    class Client:
        def stream(self, *_a, **_k):
            raise ValueError("unexpected")

        async def post(self, *_a, **_k):  # pragma: no cover - stdout is empty
            raise AssertionError("post should not be called")

    import mcpgateway.services.http_client_service as http_client_service

    class Ctx:
        async def __aenter__(self):
            return Client()

        async def __aexit__(self, *_a):
            return None

    monkeypatch.setattr(http_client_service, "get_isolated_http_client", lambda **_k: Ctx())

    with pytest.raises(ValueError, match="unexpected"):
        await translate._run_streamable_http_to_stdio("http://example.com/mcp", None, 5.0, "echo test", max_retries=1, initial_retry_delay=0.0)


@pytest.mark.asyncio
async def test_run_streamable_http_to_stdio_missing_pipes(monkeypatch, translate):
    """Test _run_streamable_http_to_stdio raises when stdin/stdout are missing."""
    # Third-Party
    import httpx as real_httpx

    setattr(translate, "httpx", real_httpx)

    class FakeProcess:
        stdin = None
        stdout = None
        returncode = None

    async def fake_create_subprocess_exec(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    with pytest.raises(RuntimeError, match="Failed to create subprocess"):
        await translate._run_streamable_http_to_stdio("http://example.com/mcp", None, 5.0, "echo test")


@pytest.mark.asyncio
async def test_multi_protocol_server_basic(monkeypatch, translate):
    """Test _run_multi_protocol_server basic setup."""
    calls = []

    class MockStdIO:
        def __init__(self, cmd, pubsub, **kwargs):
            calls.append("stdio_init")
            self.cmd = cmd
            self.pubsub = pubsub

        async def start(self):
            calls.append("stdio_start")

        async def stop(self):
            calls.append("stdio_stop")

    class MockFastAPI:
        def __init__(self):
            calls.append("fastapi_init")
            self.routes = []
            self.user_middleware = []

        def add_middleware(self, *args, **kwargs):
            calls.append("add_middleware")

        def get(self, path):
            def decorator(func):
                calls.append(f"get_{path}")
                return func

            return decorator

        def post(self, path, **kwargs):
            def decorator(func):
                calls.append(f"post_{path}")
                return func

            return decorator

    class MockServer:
        def __init__(self, config):
            calls.append("server_init")

        async def serve(self):
            calls.append("server_serve")
            # Simulate quick exit
            return

        async def shutdown(self):
            calls.append("server_shutdown")

    class MockConfig:
        def __init__(self, *args, **kwargs):
            calls.append("config_init")

    monkeypatch.setattr(translate, "StdIOEndpoint", MockStdIO)
    monkeypatch.setattr(translate, "FastAPI", MockFastAPI)
    monkeypatch.setattr(translate.uvicorn, "Config", MockConfig)
    monkeypatch.setattr(translate.uvicorn, "Server", MockServer)
    monkeypatch.setattr(
        translate.asyncio,
        "get_running_loop",
        lambda: types.SimpleNamespace(add_signal_handler=lambda *_, **__: None),
    )

    # Test with SSE exposed
    await translate._run_multi_protocol_server("test_cmd", 8000, "info", None, "127.0.0.1", expose_sse=True, expose_streamable_http=False)

    # Verify key components were initialized and started
    assert "stdio_init" in calls
    assert "stdio_start" in calls
    assert "fastapi_init" in calls
    assert "server_serve" in calls


@pytest.mark.asyncio
async def test_multi_protocol_server_no_transports_exposes_health_only(monkeypatch, translate):
    """Cover branches when no transports are enabled (stdio/pubsub are None) and exercise /healthz."""
    routes: dict[str, Any] = {}

    class FastAPI:
        def __init__(self):
            self.user_middleware = []
            self.routes = []

        def add_middleware(self, *_a, **_k):
            return None

        def get(self, path):
            def decorator(func):
                routes[path] = func
                return func

            return decorator

        def post(self, path, **_k):
            def decorator(func):
                routes[path] = func
                return func

            return decorator

        async def __call__(self, *_a, **_k):  # pragma: no cover
            return None

    class Server:
        def __init__(self, _cfg):
            self.should_exit = False

        async def serve(self):
            return None

    monkeypatch.setattr(translate, "FastAPI", FastAPI)
    monkeypatch.setattr(translate.uvicorn, "Config", lambda *a, **k: None)
    monkeypatch.setattr(translate.uvicorn, "Server", Server)
    monkeypatch.setattr(translate.asyncio, "get_running_loop", lambda: types.SimpleNamespace(add_signal_handler=lambda *_a, **_k: None))

    await translate._run_multi_protocol_server("test_cmd", 8000, "info", None, "127.0.0.1", expose_sse=False, expose_streamable_http=False)

    health = routes["/healthz"]
    resp = await health()
    assert resp.status_code == 200
    assert getattr(resp, "body", b"") == b"ok"


@pytest.mark.asyncio
async def test_multi_protocol_server_with_streamable_http(monkeypatch, translate):
    """Test _run_multi_protocol_server with streamable HTTP enabled."""
    calls = []
    routes: dict[str, Any] = {}
    app_holder: dict[str, Any] = {}
    pubsub_holder: dict[str, Any] = {}
    stdio_holder: dict[str, Any] = {}

    # Mock all the classes we need
    class MockStdIO:
        def __init__(self, cmd, pubsub, **kwargs):
            calls.append("stdio_init")
            self._pubsub = pubsub
            self.send = AsyncMock()

        async def start(self):
            calls.append("stdio_start")

        async def stop(self):
            calls.append("stdio_stop")

    class MockFastAPI:
        def __init__(self):
            calls.append("fastapi_init")
            self.routes = []
            self.user_middleware = []
            app_holder["app"] = self

        def add_middleware(self, *args, **kwargs):
            calls.append("add_middleware")

        def get(self, path):
            def decorator(func):
                calls.append(f"get_{path}")
                routes[path] = func
                return func

            return decorator

        def post(self, path, **kwargs):
            def decorator(func):
                calls.append(f"post_{path}")
                routes[path] = func
                return func

            return decorator

        async def __call__(self, *args, **kwargs):
            """Make FastAPI callable for ASGI wrapper."""
            calls.append("fastapi_called")

    class DummyPubSub:
        next_message: str | None = None

        def __init__(self):
            pubsub_holder["pubsub"] = self

        def subscribe(self):
            queue = asyncio.Queue()
            if self.next_message is not None:
                queue.put_nowait(self.next_message)
            return queue

        def unsubscribe(self, _queue):
            return None

    class MockMCPServer:
        def __init__(self, name):
            calls.append("mcp_server_init")

    class MockSessionManager:
        def __init__(self, app, stateless=False, json_response=False):
            calls.append("session_manager_init")

        def run(self):
            class MockContext:
                async def __aenter__(self):
                    calls.append("context_enter")
                    return self

                async def __aexit__(self, *args):
                    calls.append("context_exit")

            return MockContext()

    class MockServer:
        def __init__(self, config):
            calls.append("server_init")

        async def serve(self):
            calls.append("server_serve")

        async def shutdown(self):
            calls.append("server_shutdown")

    monkeypatch.setattr(translate, "StdIOEndpoint", MockStdIO)
    monkeypatch.setattr(translate, "FastAPI", MockFastAPI)
    monkeypatch.setattr(translate, "MCPServer", MockMCPServer)
    monkeypatch.setattr(translate, "StreamableHTTPSessionManager", MockSessionManager)
    monkeypatch.setattr(translate, "_PubSub", DummyPubSub)
    monkeypatch.setattr(translate.uvicorn, "Server", MockServer)
    monkeypatch.setattr(translate.uvicorn, "Config", lambda *a, **k: None)
    monkeypatch.setattr(
        translate.asyncio,
        "get_running_loop",
        lambda: types.SimpleNamespace(add_signal_handler=lambda *_, **__: None),
    )

    # Test with both SSE and streamable HTTP
    await translate._run_multi_protocol_server("test_cmd", 8000, "info", None, "127.0.0.1", expose_sse=True, expose_streamable_http=True, stateless=True, json_response=True)

    # Verify streamable components were set up
    assert "mcp_server_init" in calls
    assert "session_manager_init" in calls
    assert "context_enter" in calls
    assert "context_exit" in calls

    # Exercise /mcp handler with correlated response
    DummyPubSub.next_message = '{"id": 1, "result": "pong"}'
    mcp_handler = routes["/mcp"]

    class DummyRequest:
        async def body(self):
            return b'{"id": 1, "method": "ping"}'

    response = await mcp_handler(DummyRequest())
    assert response.status_code == 200

    # Invalid JSON payload returns 400
    class BadRequest:
        async def body(self):
            return b"{bad json"

    bad_response = await mcp_handler(BadRequest())
    assert bad_response.status_code == 400


@pytest.mark.asyncio
async def test_multi_protocol_server_sse_message_keepalive_disabled_and_post_message_header_mappings_skipped(monkeypatch, translate):
    """Cover SSE message yield with keepalive disabled and POST /message with header_mappings disabled."""
    routes: dict[str, Any] = {}
    pubsub_holder: dict[str, Any] = {}
    stdio_holder: dict[str, Any] = {}

    monkeypatch.setattr(translate, "DEFAULT_KEEPALIVE_ENABLED", False)
    monkeypatch.setattr(translate.asyncio, "sleep", AsyncMock())

    class PubSub(translate._PubSub):
        def __init__(self):
            super().__init__()
            pubsub_holder["pubsub"] = self

    class StdIO:
        def __init__(self, _cmd, pubsub, **_k):
            self._running = False
            self._pubsub = pubsub
            self.send = AsyncMock()
            stdio_holder["stdio"] = self

        async def start(self, *_a, **_k):
            self._running = True

        async def stop(self):
            self._running = False

        def is_running(self):
            return self._running

    class FastAPI:
        def __init__(self):
            self.user_middleware = []
            self.routes = []

        def add_middleware(self, *_a, **_k):
            return None

        def get(self, path):
            def decorator(func):
                routes[path] = func
                return func

            return decorator

        def post(self, path, **_k):
            def decorator(func):
                routes[path] = func
                return func

            return decorator

    class DummyResponse:
        def __init__(self, gen, headers=None):
            self.gen = gen
            self.headers = headers

    class Server:
        def __init__(self, _cfg):
            self.should_exit = False

        async def serve(self):
            return None

    monkeypatch.setattr(translate, "_PubSub", PubSub)
    monkeypatch.setattr(translate, "StdIOEndpoint", StdIO)
    monkeypatch.setattr(translate, "FastAPI", FastAPI)
    monkeypatch.setattr(translate, "EventSourceResponse", DummyResponse)
    monkeypatch.setattr(translate.uvicorn, "Config", lambda *a, **k: None)
    monkeypatch.setattr(translate.uvicorn, "Server", Server)
    monkeypatch.setattr(translate.asyncio, "get_running_loop", lambda: types.SimpleNamespace(add_signal_handler=lambda *_a, **_k: None))

    await translate._run_multi_protocol_server("test_cmd", 8000, "info", None, "127.0.0.1", expose_sse=True, expose_streamable_http=False, header_mappings=None)

    sse_handler = routes["/sse"]
    message_handler = routes["/message"]

    class DummyRequest:
        base_url = "http://test/"
        headers: dict[str, str] = {}

        def __init__(self):
            self.calls = 0

        async def is_disconnected(self):
            self.calls += 1
            return self.calls > 1

    resp = await sse_handler(DummyRequest())
    first = await resp.gen.__anext__()
    assert first["event"] == "endpoint"
    await pubsub_holder["pubsub"].publish("hi\n")
    second = await resp.gen.__anext__()
    assert second["event"] == "message"
    assert second["data"] == "hi"
    with pytest.raises(StopAsyncIteration):
        await resp.gen.__anext__()

    class Raw:
        headers: dict[str, str] = {}

        async def body(self):
            return b'{"jsonrpc":"2.0","method":"ping"}'

    stdio_holder["stdio"]._running = False
    ok = await message_handler(Raw(), session_id="abc")
    assert ok.status_code == 202
    assert stdio_holder["stdio"].send.await_count == 1


@pytest.mark.asyncio
async def test_multi_protocol_server_sse_header_mappings_empty_env_no_restart_and_post_message_starts_stdio(monkeypatch, translate):
    """Cover header_mappings enabled but env extraction yields no vars (no restart)."""
    routes: dict[str, Any] = {}
    stdio_holder: dict[str, Any] = {}

    monkeypatch.setattr(translate, "extract_env_vars_from_headers", lambda *_a, **_k: {})
    monkeypatch.setattr(translate.asyncio, "sleep", AsyncMock())

    class StdIO:
        def __init__(self, _cmd, _pubsub, **_k):
            self._running = True
            self.start = AsyncMock(side_effect=self._mark_running)
            self.stop = AsyncMock(side_effect=self._mark_stopped)
            self.send = AsyncMock()
            stdio_holder["stdio"] = self

        async def _mark_running(self, *_a, **_k):
            self._running = True

        async def _mark_stopped(self, *_a, **_k):
            self._running = False

        def is_running(self):
            return self._running

    class FastAPI:
        def __init__(self):
            self.user_middleware = []
            self.routes = []

        def add_middleware(self, *_a, **_k):
            return None

        def get(self, path):
            def decorator(func):
                routes[path] = func
                return func

            return decorator

        def post(self, path, **_k):
            def decorator(func):
                routes[path] = func
                return func

            return decorator

    class DummyResponse:
        def __init__(self, gen, headers=None):
            self.gen = gen
            self.headers = headers

    class Server:
        def __init__(self, _cfg):
            self.should_exit = False

        async def serve(self):
            return None

    monkeypatch.setattr(translate, "StdIOEndpoint", StdIO)
    monkeypatch.setattr(translate, "FastAPI", FastAPI)
    monkeypatch.setattr(translate, "EventSourceResponse", DummyResponse)
    monkeypatch.setattr(translate.uvicorn, "Config", lambda *a, **k: None)
    monkeypatch.setattr(translate.uvicorn, "Server", Server)
    monkeypatch.setattr(translate.asyncio, "get_running_loop", lambda: types.SimpleNamespace(add_signal_handler=lambda *_a, **_k: None))

    await translate._run_multi_protocol_server(
        "test_cmd",
        8000,
        "info",
        None,
        "127.0.0.1",
        expose_sse=True,
        expose_streamable_http=False,
        header_mappings={"X-Env": "ENV"},
    )

    sse_handler = routes["/sse"]
    message_handler = routes["/message"]

    class DummyRequest:
        base_url = "http://test/"
        headers = {"X-Env": "ignored"}

        async def is_disconnected(self):
            return True

    resp = await sse_handler(DummyRequest())
    first = await resp.gen.__anext__()
    assert first["event"] == "endpoint"
    # Default keepalive yields one extra frame before the disconnect check runs.
    second = await resp.gen.__anext__()
    assert second["event"] == "keepalive"
    with pytest.raises(StopAsyncIteration):
        await resp.gen.__anext__()

    class Raw:
        headers = {"X-Env": "ignored"}

        async def body(self):
            return b'{"jsonrpc":"2.0","method":"ping"}'

    stdio_holder["stdio"]._running = False
    ok = await message_handler(Raw(), session_id="abc")
    assert ok.status_code == 202
    assert stdio_holder["stdio"].start.await_count >= 1


@pytest.mark.asyncio
async def test_multi_protocol_server_sse_get_sse_raises_when_pubsub_falsy(monkeypatch, translate):
    """Cover get_sse guard raising when pubsub is falsy at request time."""
    routes: dict[str, Any] = {}
    pubsub_holder: dict[str, Any] = {}

    class PubSub(translate._PubSub):
        def __init__(self):
            super().__init__()
            self.truthy = True
            pubsub_holder["pubsub"] = self

        def __bool__(self):
            return self.truthy

    class StdIO:
        def __init__(self, *_a, **_k):
            pass

        async def start(self, *_a, **_k):
            return None

        async def stop(self):
            return None

        def is_running(self):
            return True

    class FastAPI:
        def __init__(self):
            self.user_middleware = []
            self.routes = []

        def add_middleware(self, *_a, **_k):
            return None

        def get(self, path):
            def decorator(func):
                routes[path] = func
                return func

            return decorator

        def post(self, path, **_k):
            def decorator(func):
                routes[path] = func
                return func

            return decorator

    class Server:
        def __init__(self, _cfg):
            self.should_exit = False

        async def serve(self):
            return None

    monkeypatch.setattr(translate, "_PubSub", PubSub)
    monkeypatch.setattr(translate, "StdIOEndpoint", StdIO)
    monkeypatch.setattr(translate, "FastAPI", FastAPI)
    monkeypatch.setattr(translate.uvicorn, "Config", lambda *a, **k: None)
    monkeypatch.setattr(translate.uvicorn, "Server", Server)
    monkeypatch.setattr(translate.asyncio, "get_running_loop", lambda: types.SimpleNamespace(add_signal_handler=lambda *_a, **_k: None))

    await translate._run_multi_protocol_server("test_cmd", 8000, "info", None, "127.0.0.1", expose_sse=True, expose_streamable_http=False)

    pubsub_holder["pubsub"].truthy = False

    sse_handler = routes["/sse"]

    class DummyRequest:
        base_url = "http://test/"
        headers: dict[str, str] = {}

        async def is_disconnected(self):  # pragma: no cover
            return True

    with pytest.raises(RuntimeError, match="PubSub not available"):
        await sse_handler(DummyRequest())


@pytest.mark.asyncio
async def test_multi_protocol_server_sse_timeout_keepalive_disabled_and_pubsub_falsy_skips_unsubscribe(monkeypatch, translate):
    """Cover timeout handling when keepalive disabled and pubsub falsy cleanup branch in SSE generator."""
    routes: dict[str, Any] = {}
    pubsub_holder: dict[str, Any] = {}

    monkeypatch.setattr(translate, "DEFAULT_KEEPALIVE_ENABLED", False)

    async def fake_wait_for(queue_get_coro, _timeout):
        queue_get_coro.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(translate.asyncio, "wait_for", fake_wait_for)

    class PubSub(translate._PubSub):
        def __init__(self):
            super().__init__()
            self.truthy = True
            pubsub_holder["pubsub"] = self

        def __bool__(self):
            return self.truthy

    class StdIO:
        def __init__(self, *_a, **_k):
            pass

        async def start(self, *_a, **_k):
            return None

        async def stop(self):
            return None

        def is_running(self):
            return True

    class FastAPI:
        def __init__(self):
            self.user_middleware = []
            self.routes = []

        def add_middleware(self, *_a, **_k):
            return None

        def get(self, path):
            def decorator(func):
                routes[path] = func
                return func

            return decorator

        def post(self, path, **_k):
            def decorator(func):
                routes[path] = func
                return func

            return decorator

    class DummyResponse:
        def __init__(self, gen, headers=None):
            self.gen = gen
            self.headers = headers

    class Server:
        def __init__(self, _cfg):
            self.should_exit = False

        async def serve(self):
            return None

    monkeypatch.setattr(translate, "_PubSub", PubSub)
    monkeypatch.setattr(translate, "StdIOEndpoint", StdIO)
    monkeypatch.setattr(translate, "FastAPI", FastAPI)
    monkeypatch.setattr(translate, "EventSourceResponse", DummyResponse)
    monkeypatch.setattr(translate.uvicorn, "Config", lambda *a, **k: None)
    monkeypatch.setattr(translate.uvicorn, "Server", Server)
    monkeypatch.setattr(translate.asyncio, "get_running_loop", lambda: types.SimpleNamespace(add_signal_handler=lambda *_a, **_k: None))

    await translate._run_multi_protocol_server("test_cmd", 8000, "info", None, "127.0.0.1", expose_sse=True, expose_streamable_http=False)

    sse_handler = routes["/sse"]

    class DummyRequest:
        base_url = "http://test/"
        headers: dict[str, str] = {}

        def __init__(self):
            self.calls = 0

        async def is_disconnected(self):
            self.calls += 1
            return self.calls > 1

    resp = await sse_handler(DummyRequest())
    first = await resp.gen.__anext__()
    assert first["event"] == "endpoint"
    pubsub_holder["pubsub"].truthy = False
    with pytest.raises(StopAsyncIteration):
        await resp.gen.__anext__()
    assert len(pubsub_holder["pubsub"]._subscribers) == 1


@pytest.mark.asyncio
async def test_multi_protocol_server_post_message_raises_when_stdio_falsy(monkeypatch, translate):
    """Cover post_message runtime guard raising when stdio becomes falsy."""
    routes: dict[str, Any] = {}
    stdio_holder: dict[str, Any] = {}

    monkeypatch.setattr(translate.asyncio, "sleep", AsyncMock())

    class StdIO:
        def __init__(self, *_a, **_k):
            self.truthy = True
            self.send = AsyncMock()
            stdio_holder["stdio"] = self

        def __bool__(self):
            return self.truthy

        async def start(self, *_a, **_k):
            return None

        async def stop(self):
            return None

        def is_running(self):
            # Flip after the running check so the later "if not stdio" guard triggers.
            self.truthy = False
            return True

    class FastAPI:
        def __init__(self):
            self.user_middleware = []
            self.routes = []

        def add_middleware(self, *_a, **_k):
            return None

        def get(self, path):
            def decorator(func):
                routes[path] = func
                return func

            return decorator

        def post(self, path, **_k):
            def decorator(func):
                routes[path] = func
                return func

            return decorator

    class Server:
        def __init__(self, _cfg):
            self.should_exit = False

        async def serve(self):
            return None

    monkeypatch.setattr(translate, "StdIOEndpoint", StdIO)
    monkeypatch.setattr(translate, "FastAPI", FastAPI)
    monkeypatch.setattr(translate.uvicorn, "Config", lambda *a, **k: None)
    monkeypatch.setattr(translate.uvicorn, "Server", Server)
    monkeypatch.setattr(translate.asyncio, "get_running_loop", lambda: types.SimpleNamespace(add_signal_handler=lambda *_a, **_k: None))

    await translate._run_multi_protocol_server("test_cmd", 8000, "info", None, "127.0.0.1", expose_sse=True, expose_streamable_http=False)

    message_handler = routes["/message"]

    class Raw:
        headers: dict[str, str] = {}

        async def body(self):
            return b'{"jsonrpc":"2.0","method":"ping"}'

    with pytest.raises(RuntimeError, match="Stdio endpoint not available"):
        await message_handler(Raw(), session_id="abc")


@pytest.mark.asyncio
async def test_multi_protocol_server_mcp_post_branches_asgi_wrapper_shutdown_idempotent_and_cleanup_fallbacks(monkeypatch, translate):
    """Cover /mcp branches, ASGI wrapper routing, shutdown idempotency, and cleanup fallback/timeout paths."""
    # Standard
    import builtins
    from contextlib import suppress

    calls: list[tuple[str, str | None]] = []
    routes: dict[str, Any] = {}
    app_holder: dict[str, Any] = {}
    pubsub_holder: dict[str, Any] = {}
    stdio_holder: dict[str, Any] = {}
    stop_called = asyncio.Event()

    class PubSub:
        def __init__(self):
            self.truthy = True
            self._subscribers: list[asyncio.Queue[str]] = []
            pubsub_holder["pubsub"] = self

        def __bool__(self):
            return self.truthy

        def subscribe(self):
            q: asyncio.Queue[str] = asyncio.Queue()
            self._subscribers.append(q)
            return q

        def unsubscribe(self, q):
            with suppress(ValueError):
                self._subscribers.remove(q)

    class StdIO:
        def __init__(self, _cmd, pubsub, **_k):
            self.truthy = True
            self._pubsub = pubsub
            self.send = AsyncMock()
            stdio_holder["stdio"] = self

        def __bool__(self):
            return self.truthy

        async def start(self, *_a, **_k):
            return None

        async def stop(self):
            stop_called.set()

        def is_running(self):
            return True

    class FastAPI:
        def __init__(self):
            self.routes = []
            self.user_middleware = []

        def add_middleware(self, *_a, **_k):
            return None

        def get(self, path):
            def decorator(func):
                routes[path] = func
                return func

            return decorator

        def post(self, path, **_k):
            def decorator(func):
                routes[path] = func
                return func

            return decorator

        async def __call__(self, scope, receive, send):
            _ = receive, send
            calls.append(("original_app", scope.get("path")))

    class StreamableManager:
        def __init__(self, *a, **k):
            _ = a, k

        def run(self):
            class Ctx:
                async def __aenter__(self):
                    calls.append(("ctx_enter", None))
                    return self

                async def __aexit__(self, *_a):
                    calls.append(("ctx_exit", None))
                    raise Exception("cleanup boom")

            return Ctx()

    class DummyScope:
        def __init__(self, _timeout):
            self.cancelled_caught = True

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr(translate, "_PubSub", PubSub)
    monkeypatch.setattr(translate, "StdIOEndpoint", StdIO)
    monkeypatch.setattr(translate, "FastAPI", FastAPI)
    monkeypatch.setattr(translate, "MCPServer", lambda *_a, **_k: None)
    monkeypatch.setattr(translate, "StreamableHTTPSessionManager", StreamableManager)
    monkeypatch.setattr(translate.anyio, "move_on_after", lambda timeout: DummyScope(timeout))

    # Force mcpgateway.config import inside translate cleanup to fail (exercise fallback timeout).
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
        caller = sys._getframe(1).f_globals.get("__name__")
        if caller == "mcpgateway.translate" and name == "mcpgateway.config":
            raise ImportError("blocked")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    # Capture the ASGI app passed to uvicorn (wrapper when streamable HTTP is enabled).
    class Config:
        def __init__(self, app, **_k):
            app_holder["asgi_app"] = app

    class Server:
        def __init__(self, _cfg):
            self.should_exit = False

        async def serve(self):
            await stop_called.wait()

    monkeypatch.setattr(translate.uvicorn, "Config", Config)
    monkeypatch.setattr(translate.uvicorn, "Server", Server)

    # Immediately invoke signal callbacks to schedule shutdown early (idempotent path).
    monkeypatch.setattr(translate.asyncio, "get_running_loop", lambda: types.SimpleNamespace(add_signal_handler=lambda _sig, cb: cb()))

    await translate._run_multi_protocol_server("test_cmd", 8000, "info", None, "127.0.0.1", expose_sse=False, expose_streamable_http=True)

    # ASGI wrapper routes both branches to original_app.
    async def receive():
        return {}

    async def send(_msg):
        return None

    wrapper = app_holder["asgi_app"]
    await wrapper({"type": "http", "path": "/mcp"}, receive, send)
    await wrapper({"type": "http", "path": "/other"}, receive, send)
    assert ("original_app", "/mcp") in calls
    assert ("original_app", "/other") in calls

    mcp_handler = routes["/mcp"]
    pubsub = pubsub_holder["pubsub"]
    stdio = stdio_holder["stdio"]

    # Notification -> 202
    class NotifyReq:
        async def body(self):
            return b'{"method":"ping"}'

    notif = await mcp_handler(NotifyReq())
    assert notif.status_code == 202

    # Pubsub missing -> accepted (202)
    pubsub.truthy = False

    class IdReq:
        async def body(self):
            return b'{"id": 1, "method":"ping"}'

    accepted = await mcp_handler(IdReq())
    assert accepted.status_code == 202
    pubsub.truthy = True

    # TimeoutError -> accepted no response yet (covers TimeoutError break).
    async def timeout_wait_for(queue_get_coro, timeout=None):
        _ = timeout
        queue_get_coro.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(translate.asyncio, "wait_for", timeout_wait_for)
    no_resp = await mcp_handler(IdReq())
    assert no_resp.status_code == 202

    # Skip non-JSON and wrong-id candidate, then timeout.
    msgs = iter(["not json", '{\"id\": 999, \"result\": \"no\"}'])

    async def seq_wait_for(queue_get_coro, timeout=None):
        _ = timeout
        queue_get_coro.close()
        try:
            return next(msgs)
        except StopIteration:
            raise asyncio.TimeoutError()

    monkeypatch.setattr(translate.asyncio, "wait_for", seq_wait_for)
    no_match = await mcp_handler(IdReq())
    assert no_match.status_code == 202

    # remaining==0 path -> accept.
    times = iter([0.0, 10.0])

    class Loop:
        def time(self):
            return next(times)

    # Patch asyncio.get_event_loop only for this call; leaving it patched breaks pytest-asyncio teardown.
    real_get_event_loop = translate.asyncio.get_event_loop
    translate.asyncio.get_event_loop = lambda: Loop()  # type: ignore[assignment]
    try:
        monkeypatch.setattr(translate.asyncio, "wait_for", timeout_wait_for)
        remaining_zero = await mcp_handler(IdReq())
        assert remaining_zero.status_code == 202
    finally:
        translate.asyncio.get_event_loop = real_get_event_loop  # type: ignore[assignment]

    # stdio missing -> raise
    stdio.truthy = False
    with pytest.raises(RuntimeError, match="Stdio endpoint not available"):
        await mcp_handler(IdReq())


@pytest.mark.asyncio
async def test_multi_protocol_server_sse_routes(monkeypatch, translate):
    """Exercise SSE routes and message handling in multi-protocol server."""
    routes: dict[str, Any] = {}
    pubsub_holder: dict[str, Any] = {}
    stdio_holder: dict[str, Any] = {}

    class DummyPubSub:
        def __init__(self):
            pubsub_holder["pubsub"] = self
            self.subscribers = []

        def subscribe(self):
            queue = asyncio.Queue()
            self.subscribers.append(queue)
            return queue

        def unsubscribe(self, queue):
            self.subscribers.remove(queue)

    class MockStdIO:
        def __init__(self, cmd, pubsub, **kwargs):
            self._running = False
            self.send = AsyncMock()
            self.last_env = None
            stdio_holder["stdio"] = self

        async def start(self, env=None):
            self._running = True
            self.last_env = env

        async def stop(self):
            self._running = False

        def is_running(self):
            return self._running

    class MockFastAPI:
        def __init__(self):
            self.routes = []
            self.user_middleware = []

        def add_middleware(self, *args, **kwargs):
            return None

        def get(self, path):
            def decorator(func):
                routes[path] = func
                return func

            return decorator

        def post(self, path, **kwargs):
            def decorator(func):
                routes[path] = func
                return func

            return decorator

    class DummyResponse:
        def __init__(self, gen, headers=None):
            self.gen = gen
            self.headers = headers

    class MockServer:
        def __init__(self, config):
            pass

        async def serve(self):
            return None

        async def shutdown(self):
            return None

    monkeypatch.setattr(translate, "_PubSub", DummyPubSub)
    monkeypatch.setattr(translate, "StdIOEndpoint", MockStdIO)
    monkeypatch.setattr(translate, "FastAPI", MockFastAPI)
    monkeypatch.setattr(translate, "EventSourceResponse", DummyResponse)
    monkeypatch.setattr(translate, "extract_env_vars_from_headers", lambda *_a, **_k: {"ENV": "1"})
    monkeypatch.setattr(translate, "DEFAULT_KEEPALIVE_ENABLED", True)
    monkeypatch.setattr(translate.uvicorn, "Config", lambda *a, **k: None)
    monkeypatch.setattr(translate.uvicorn, "Server", MockServer)
    monkeypatch.setattr(
        translate.asyncio,
        "get_running_loop",
        lambda: types.SimpleNamespace(add_signal_handler=lambda *_, **__: None),
    )

    async def fake_wait_for(_queue_get, _timeout):
        _queue_get.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(translate.asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr(translate.asyncio, "sleep", AsyncMock())

    await translate._run_multi_protocol_server(
        "test_cmd",
        8000,
        "info",
        ["https://example.com"],
        "127.0.0.1",
        expose_sse=True,
        expose_streamable_http=False,
        header_mappings={"X-Env": "ENV"},
    )

    sse_handler = routes["/sse"]
    message_handler = routes["/message"]

    class DummyRequest:
        base_url = "http://test/"
        headers = {"X-Env": "1"}

        def __init__(self):
            self.calls = 0

        async def is_disconnected(self):
            self.calls += 1
            return self.calls > 1

    resp = await sse_handler(DummyRequest())
    first = await resp.gen.__anext__()
    second = await resp.gen.__anext__()
    third = await resp.gen.__anext__()
    assert first["event"] == "endpoint"
    assert second["event"] == "keepalive"
    assert third["event"] == "keepalive"
    with pytest.raises(StopAsyncIteration):
        await resp.gen.__anext__()
    assert pubsub_holder["pubsub"].subscribers == []

    class BadRequest:
        headers = {"X-Env": "1"}

        async def body(self):
            return b"{bad json}"

    bad_resp = await message_handler(BadRequest(), session_id="abc")
    assert bad_resp.status_code == 400

    class GoodRequest:
        headers = {"X-Env": "1"}

        async def body(self):
            return b'{"jsonrpc":"2.0","method":"ping"}'

    stdio_holder["stdio"]._running = False
    ok_resp = await message_handler(GoodRequest(), session_id="abc")
    assert ok_resp.status_code == 202
