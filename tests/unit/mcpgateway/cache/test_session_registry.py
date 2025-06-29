# -*- coding: utf-8 -*-
"""Memory-backend unit tests for ``session_registry.py``.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This suite exercises the in-memory implementation of
:pyfile:`mcpgateway/cache/session_registry.py`.

Covered behaviours
------------------
* add_session / get_session / get_session_sync / remove_session
* broadcast -> respond for **dict**, **list**, **str** payloads
* generate_response branches:
  • initialize (result + notifications)
  • ping
  • tools/list (with stubbed service + DB)
* handle_initialize_logic success, and both error branches
"""

# Future
from __future__ import annotations

# Standard
import asyncio
import json
import re
from typing import Any, Dict, List

# Third-Party
from fastapi import HTTPException
import pytest

# Prefer installed package; otherwise fall back to local file when running
# outside the project tree (keeps tests developer-friendly).
try:
    # First-Party
    from mcpgateway.cache.session_registry import SessionRegistry
    from mcpgateway.config import settings
except (ModuleNotFoundError, ImportError):  # pragma: no cover
    # Third-Party
    from session_registry import SessionRegistry  # type: ignore

    settings = type(
        "S",
        (),
        {
            "protocol_version": "1.0",
            "federation_timeout": 1,
            "skip_ssl_verify": True,
        },
    )


# --------------------------------------------------------------------------- #
# Minimal SSE transport stub                                                  #
# --------------------------------------------------------------------------- #
class FakeSSETransport:
    """Stub implementing just the subset of the API used by SessionRegistry."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._connected = True
        self.sent: List[Any] = []

    async def disconnect(self) -> None:  # noqa: D401
        self._connected = False

    async def is_connected(self) -> bool:  # noqa: D401
        return self._connected

    async def send_message(self, msg) -> None:  # noqa: D401
        # Deep-copy through JSON round-trip for realism
        self.sent.append(json.loads(json.dumps(msg)))


# --------------------------------------------------------------------------- #
# Event-loop fixture (pytest default loop is function-scoped)                 #
# --------------------------------------------------------------------------- #
@pytest.fixture(name="event_loop")
def _event_loop_fixture():
    """Provide a fresh asyncio loop for these async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# --------------------------------------------------------------------------- #
# SessionRegistry fixture (memory backend)                                    #
# --------------------------------------------------------------------------- #
@pytest.fixture()
async def registry() -> SessionRegistry:
    """Initialise an in-memory SessionRegistry and tear it down after tests."""
    reg = SessionRegistry(backend="memory")
    await reg.initialize()
    yield reg
    await reg.shutdown()


# --------------------------------------------------------------------------- #
# Core CRUD behaviour                                                         #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_add_get_remove(registry: SessionRegistry):
    """Add ➜ get (async & sync) ➜ remove and verify cache/state."""
    tr = FakeSSETransport("A")
    await registry.add_session("A", tr)

    assert await registry.get_session("A") is tr
    assert registry.get_session_sync("A") is tr
    assert await registry.get_session("missing") is None

    # Remove twice – second call must be harmless
    await registry.remove_session("A")
    await registry.remove_session("A")

    assert not await tr.is_connected()
    assert registry.get_session_sync("A") is None


# --------------------------------------------------------------------------- #
# broadcast ➜ respond with different payload types                            #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"method": "ping", "id": 1, "params": {}},  # dict
        ["x", "y", 42],  # list
        "plain-string",  # str
    ],
)
async def test_broadcast_and_respond(payload, monkeypatch, registry: SessionRegistry):
    """broadcast stores the payload; respond routes it to generate_response."""
    tr = FakeSSETransport("B")
    await registry.add_session("B", tr)

    captured: Dict[str, Any] = {}

    # Patch generate_response so we can verify it's called with our payload:
    async def fake_generate_response(*, message, transport, **kwargs):  # noqa: D401
        captured["message"] = message
        captured["transport"] = transport
        captured["kwargs"] = kwargs

    monkeypatch.setattr(registry, "generate_response", fake_generate_response)

    await registry.broadcast("B", payload)
    await registry.respond(server_id=None, user={}, session_id="B", base_url="http://localhost")

    assert captured["transport"] is tr
    assert captured["message"] == payload


# --------------------------------------------------------------------------- #
# Fixtures to stub get_db and the three *Service objects                      #
# --------------------------------------------------------------------------- #
@pytest.fixture()
def stub_db(monkeypatch):
    """Patch ``get_db`` to return a synchronous dummy iterator."""

    def _dummy_iter():
        yield None

    monkeypatch.setattr(
        "mcpgateway.cache.session_registry.get_db",
        lambda: _dummy_iter(),
        raising=False,
    )


@pytest.fixture()
def stub_services(monkeypatch):
    """Replace list_* service methods so they return predictable data."""

    class _Item:
        def model_dump(self, *_, **__) -> Dict[str, str]:  # noqa: D401
            return {"name": "demo"}

    async def _return_items(*args, **kwargs):  # noqa: D401
        return [_Item()]

    mod = "mcpgateway.cache.session_registry"
    monkeypatch.setattr(f"{mod}.tool_service.list_tools", _return_items, raising=False)
    monkeypatch.setattr(f"{mod}.prompt_service.list_prompts", _return_items, raising=False)
    monkeypatch.setattr(f"{mod}.resource_service.list_resources", _return_items, raising=False)


# --------------------------------------------------------------------------- #
# generate_response branches                                                  #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_generate_response_initialize(registry: SessionRegistry):
    """The *initialize* branch sends result + notifications (>= 5 messages)."""
    tr = FakeSSETransport("init")
    await registry.add_session("init", tr)

    msg = {
        "method": "initialize",
        "id": 101,
        "params": {"protocol_version": settings.protocol_version},
    }
    await registry.generate_response(
        message=msg,
        transport=tr,
        server_id=None,
        user={},
        base_url="http://host",
    )

    # Implementation may emit 5 or 6 messages (roots/list_changed optional)
    assert len(tr.sent) >= 5

    first = tr.sent[0]
    assert first["id"] == 101
    assert first["result"]["protocolVersion"] == settings.protocol_version
    assert re.match(r"notifications/initialized$", tr.sent[1]["method"])


@pytest.mark.asyncio
async def test_generate_response_ping(registry: SessionRegistry):
    """The *ping* branch should echo an empty result."""
    tr = FakeSSETransport("ping")
    await registry.add_session("ping", tr)

    msg = {"method": "ping", "id": 77, "params": {}}
    await registry.generate_response(
        message=msg,
        transport=tr,
        server_id=None,
        user={},
        base_url="http://host",
    )

    assert tr.sent[-1] == {"jsonrpc": "2.0", "result": {}, "id": 77}


@pytest.mark.asyncio
async def test_generate_response_tools_list(registry: SessionRegistry, stub_db, stub_services):
    """*tools/list* responds with the stubbed ToolService payload."""
    tr = FakeSSETransport("tools")
    await registry.add_session("tools", tr)

    msg = {"method": "tools/list", "id": 42, "params": {}}
    await registry.generate_response(
        message=msg,
        transport=tr,
        server_id=None,
        user={},
        base_url="http://host",
    )

    reply = tr.sent[-1]
    assert reply["id"] == 42
    assert reply["result"]["tools"] == [{"name": "demo"}]


# --------------------------------------------------------------------------- #
# handle_initialize_logic success & errors                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_handle_initialize_success(registry: SessionRegistry):
    body = {"protocol_version": settings.protocol_version}
    res = await registry.handle_initialize_logic(body)
    assert res.protocol_version == settings.protocol_version


@pytest.mark.asyncio
async def test_handle_initialize_missing_version_error(registry: SessionRegistry):
    with pytest.raises(HTTPException) as exc:
        await registry.handle_initialize_logic({})
    assert exc.value.headers["MCP-Error-Code"] == "-32002"


@pytest.mark.asyncio
async def test_handle_initialize_unsupported_version_error(registry: SessionRegistry):
    body = {"protocol_version": "999"}
    with pytest.raises(HTTPException) as exc:
        await registry.handle_initialize_logic(body)
    assert exc.value.headers["MCP-Error-Code"] == "-32003"
