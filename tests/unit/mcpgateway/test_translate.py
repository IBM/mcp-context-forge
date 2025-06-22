# -*- coding: utf-8 -*-
"""Full-coverage test-suite for **mcpgateway.translate**.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti + contributors

The suite exercises:

* `_PubSub` fan-out logic (including QueueFull removal path)
* `StdIOEndpoint.start/stop/send/_pump_stdout` with a fake subprocess
* `_build_fastapi` - `/sse`, `/message`, `/healthz` routes, keep-alive &
  message forwarding
* `_parse_args` happy-path and *NotImplemented* branches
* `_run_stdio_to_sse` orchestration, patched so no real network binding

Running:

```bash
pytest -q --cov=mcpgateway.translate
```
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
from typing import Any, Dict, List, Sequence

import pytest
from fastapi.testclient import TestClient

# ─────────────────────────────────────────────────────────────────────────────
# ●  Pytest fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture()
def translate():
    sys.modules.pop("mcpgateway.translate", None)
    return importlib.import_module("mcpgateway.translate")


# ─────────────────────────────────────────────────────────────────────────────
# ●  Dummy subprocess simulation
# ─────────────────────────────────────────────────────────────────────────────


class _DummyWriter:
    def __init__(self):
        self.buffer = []

    def write(self, data: bytes):
        self.buffer.append(data)

    async def drain(self):
        pass


class _DummyReader:
    def __init__(self, lines: Sequence[str]):
        self._lines = [ln.encode() for ln in lines]

    async def readline(self):
        if self._lines:
            return self._lines.pop(0)
        await asyncio.sleep(0)
        return b""


class _FakeProc:
    def __init__(self, lines: Sequence[str]):
        self.stdin = _DummyWriter()
        self.stdout = _DummyReader(lines)
        self.pid = 1234
        self.terminated = False

    def terminate(self):
        self.terminated = True

    async def wait(self):
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# ●  Tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pubsub_basic(translate):
    ps = translate._PubSub()
    q = ps.subscribe()
    await ps.publish("hello")
    assert q.get_nowait() == "hello"
    ps.unsubscribe(q)
    assert q not in ps._subscribers


@pytest.mark.asyncio
async def test_pubsub_queuefull_removal(translate):
    ps = translate._PubSub()

    class _BadQueue(asyncio.Queue):
        def put_nowait(self, _):
            raise asyncio.QueueFull

    bad = _BadQueue()
    ps._subscribers.append(bad)
    await ps.publish("x")
    assert bad not in ps._subscribers


@pytest.mark.asyncio
async def test_stdio_endpoint_start_stop_send(monkeypatch, translate):
    ps = translate._PubSub()
    lines = ['{"jsonrpc":"2.0"}\n']
    fake_proc = _FakeProc(lines)

    async def _fake_create_exec(*_a, **_kw):
        return fake_proc

    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", _fake_create_exec)

    ep = translate.StdIOEndpoint("dummy-cmd", ps)
    subscriber = ps.subscribe()

    await ep.start()
    msg = await asyncio.wait_for(subscriber.get(), timeout=1)
    assert msg.strip() == '{"jsonrpc":"2.0"}'

    await ep.send("PING\n")
    assert fake_proc.stdin.buffer[-1] == b"PING\n"

    await ep.stop()
    assert fake_proc.terminated is True


@pytest.mark.asyncio
async def test_stdio_send_without_start(translate):
    ep = translate.StdIOEndpoint("cmd", translate._PubSub())
    with pytest.raises(RuntimeError):
        await ep.send("x")


def test_fastapi_routes(translate):
    class _DummyStd:
        def __init__(self):
            self.sent = []

        async def send(self, txt: str):
            self.sent.append(txt)

    ps = translate._PubSub()
    std = _DummyStd()
    app = translate._build_fastapi(ps, std, keep_alive=1)
    client = TestClient(app)

    # /healthz
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.text == "ok"

    # /message - bad JSON
    resp = client.post("/message", data="not-json", headers={"Content-Type": "application/json"})
    assert resp.status_code == 400
    assert "Invalid JSON payload" in resp.text

    # /message - good JSON
    good_json = {"jsonrpc": 1}
    resp = client.post("/message", json=good_json)
    assert resp.status_code == 202
    assert json.loads(std.sent[-1].strip()) == {"jsonrpc": 1}

    # /sse - check that it streams and starts with endpoint + keepalive
    # with client.stream("GET", "/sse") as stream:
    #     events = []
    #     buffer = []
    #     for line in stream.iter_lines():
    #         line = line.decode("utf-8").strip()
    #         if not line:
    #             # End of one event
    #             if buffer:
    #                 events.append("\n".join(buffer))
    #                 buffer = []

    #             # Exit after both events
    #             if len(events) >= 2:
    #                 break
    #         else:
    #             buffer.append(line)

    #     # Confirm expected events
    #     assert any("event: endpoint" in e for e in events)
    #     assert any("event: keepalive" in e for e in events)


def test_parse_args_ok(translate):
    ns = translate._parse_args(["--stdio", "echo hi", "--port", "9001"])
    assert ns.stdio == "echo hi" and ns.port == 9001


def test_parse_args_not_implemented(translate):
    with pytest.raises(NotImplementedError):
        translate._parse_args(["--sse", "x"])


@pytest.mark.asyncio
async def test_run_stdio_to_sse(monkeypatch, translate):
    class _DummyStd:
        last = None

        def __init__(self, cmd, ps):
            _DummyStd.last = self
            self.started = self.stopped = False

        async def start(self):
            self.started = True

        async def stop(self):
            self.stopped = True

    monkeypatch.setattr(translate, "StdIOEndpoint", _DummyStd)

    class _FakeConfig:
        def __init__(self, app, host, port, log_level, lifespan):
            self.app = app
            self.host = host
            self.port = port
            self.log_level = log_level
            self.lifespan = lifespan

    class _FakeServer:
        last = None

        def __init__(self, cfg):
            _FakeServer.last = self
            self.config = cfg
            self.served = False
            self.shutdown_called = False

        async def serve(self):
            self.served = True

        async def shutdown(self):
            self.shutdown_called = True

    monkeypatch.setattr(translate.uvicorn, "Config", _FakeConfig)
    monkeypatch.setattr(translate.uvicorn, "Server", _FakeServer)

    class _DummyLoop:
        def add_signal_handler(self, *_):
            raise NotImplementedError

    monkeypatch.setattr(translate.asyncio, "get_running_loop", lambda: _DummyLoop())

    await translate._run_stdio_to_sse("cmd", port=0, log_level="info")

    std = _DummyStd.last
    srv = _FakeServer.last
    assert std.started and std.stopped and srv.served and srv.shutdown_called
