# -*- coding: utf-8 -*-
"""Tests for translate module helpers."""

# Standard
from types import SimpleNamespace

# Third-Party
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import pytest
from unittest.mock import AsyncMock, MagicMock

# First-Party
from mcpgateway import translate
from mcpgateway.translate_header_utils import NormalizedMappings


@pytest.mark.asyncio
async def test_pubsub_publish_and_unsubscribe():
    pubsub = translate._PubSub()
    queue = pubsub.subscribe()
    await pubsub.publish("hello")
    assert await queue.get() == "hello"
    pubsub.unsubscribe(queue)
    pubsub.unsubscribe(queue)  # no-op on missing


def test_sse_event_parser():
    event, complete = translate.SSEEvent.parse_sse_line("event: message", None)
    assert event is not None
    assert event.event == "message"
    assert complete is False

    event, complete = translate.SSEEvent.parse_sse_line("data: first", event)
    event, complete = translate.SSEEvent.parse_sse_line("data: second", event)
    assert event.data == "first\nsecond"
    assert complete is False

    event, complete = translate.SSEEvent.parse_sse_line("id: 123", event)
    assert event.event_id == "123"

    event, complete = translate.SSEEvent.parse_sse_line("retry: 50", event)
    assert event.retry == 50

    event, complete = translate.SSEEvent.parse_sse_line("retry: invalid", event)
    assert event.retry == 50

    event, complete = translate.SSEEvent.parse_sse_line("", event)
    assert complete is True


def test_parse_args_variants():
    args = translate._parse_args(["--stdio", "cat", "--port", "9000", "--cors", "https://app.com"])
    assert args.stdio == "cat"
    assert args.port == 9000
    assert args.cors == ["https://app.com"]

    args = translate._parse_args(["--connect-sse", "http://example.com/sse", "--oauth2Bearer", "token123"])
    assert args.connect_sse == "http://example.com/sse"
    assert args.oauth2Bearer == "token123"

    args = translate._parse_args(["--stdio", "cat", "--enable-dynamic-env", "--header-to-env", "Authorization=AUTH_TOKEN"])
    assert args.enable_dynamic_env is True
    assert args.header_to_env == ["Authorization=AUTH_TOKEN"]


def test_build_fastapi_routes_and_cors():
    pubsub = translate._PubSub()
    stdio = MagicMock()
    app = translate._build_fastapi(pubsub, stdio, sse_path="/events", message_path="/send", cors_origins=["http://example.com"])
    assert isinstance(app, FastAPI)
    paths = [route.path for route in app.routes]
    assert "/events" in paths
    assert "/send" in paths
    assert "/healthz" in paths
    assert any("CORSMiddleware" in str(middleware) for middleware in app.user_middleware)


@pytest.mark.asyncio
async def test_stdio_endpoint_start_send_stop(monkeypatch):
    pubsub = translate._PubSub()
    mappings = NormalizedMappings({"X-Test": "TEST_ENV"})

    class FakeStream:
        def __init__(self):
            self.buffer = []

        def write(self, data):
            self.buffer.append(data)

        async def drain(self):
            return None

    class FakeStdout:
        async def readline(self):
            return b""

    class FakeProcess:
        def __init__(self):
            self.stdin = FakeStream()
            self.stdout = FakeStdout()
            self.pid = 123
            self.returncode = None

        def terminate(self):
            self.returncode = 0

        async def wait(self):
            return 0

    fake_proc = FakeProcess()
    create_proc = AsyncMock(return_value=fake_proc)
    monkeypatch.setattr(translate.asyncio, "create_subprocess_exec", create_proc)

    stdio = translate.StdIOEndpoint("echo hello", pubsub, env_vars={"BASE": "1"}, header_mappings=mappings)
    monkeypatch.setattr(stdio, "_pump_stdout", AsyncMock())

    monkeypatch.setenv("TEST_ENV", "secret")
    await stdio.start()
    env = create_proc.call_args.kwargs["env"]
    assert "TEST_ENV" not in env
    assert stdio.is_running() is True

    await stdio.send("ping")
    assert fake_proc.stdin.buffer[-1] == b"ping"

    await stdio.stop()
    assert stdio.is_running() is False
