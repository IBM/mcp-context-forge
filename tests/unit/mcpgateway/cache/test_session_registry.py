# -*- coding: utf-8 -*-
"""Memory-backend unit tests for `session_registry.py`.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Author: Mihai Criveti

These tests cover the essential public behaviours of SessionRegistry when
configured with backend="memory":

* add_session / get_session / get_session_sync
* remove_session (disconnects transport & clears cache)
* broadcast + respond (with generate_response monkey-patched)

No Redis or SQLAlchemy fixtures are required, making the suite fast and
portable.
"""

import asyncio

import pytest

# Import SessionRegistry – works whether the file lives inside the package or beside it
try:
    from mcpgateway.cache.session_registry import SessionRegistry
except (ModuleNotFoundError, ImportError):  # pragma: no cover
    from session_registry import SessionRegistry  # type: ignore


class FakeSSETransport:
    """Minimal stub implementing only the methods SessionRegistry uses."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._connected = True
        self.sent_messages = []

    async def disconnect(self):
        self._connected = False

    async def is_connected(self):
        return self._connected

    async def send_message(self, msg):
        self.sent_messages.append(msg)


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(name="event_loop")
def _event_loop_fixture():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture()
async def registry():
    reg = SessionRegistry(backend="memory")
    await reg.initialize()
    yield reg
    await reg.shutdown()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_and_get_session(registry):
    tr = FakeSSETransport("abc")
    await registry.add_session("abc", tr)

    assert await registry.get_session("abc") is tr
    assert registry.get_session_sync("abc") is tr


@pytest.mark.asyncio
async def test_remove_session(registry):
    tr = FakeSSETransport("dead")
    await registry.add_session("dead", tr)

    await registry.remove_session("dead")

    assert not await tr.is_connected()
    assert registry.get_session_sync("dead") is None


@pytest.mark.asyncio
async def test_broadcast_and_respond(monkeypatch, registry):
    """Ensure broadcast stores the message and respond delivers it via generate_response."""
    tr = FakeSSETransport("xyz")
    await registry.add_session("xyz", tr)

    captured = {}

    async def fake_generate_response(*, message, transport, **_):
        captured["transport"] = transport
        captured["message"] = message

    monkeypatch.setattr(registry, "generate_response", fake_generate_response)

    ping_msg = {"method": "ping", "id": 1, "params": {}}
    await registry.broadcast("xyz", ping_msg)

    # respond should call our fake_generate_response exactly once
    await registry.respond(
        server_id=None,
        user={},
        session_id="xyz",
        base_url="http://localhost",
    )

    assert captured["transport"] is tr
    assert captured["message"] == ping_msg
