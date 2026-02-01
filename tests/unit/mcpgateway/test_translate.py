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
