# -*- coding: utf-8 -*-
"""Unit tests for Federation Manager.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Test Suite

Comprehensive unit tests for the federation manager module.
"""

# Future
from __future__ import annotations

# Standard
import asyncio
from datetime import datetime
from itertools import count

# First-Party
from mcpgateway.federation.manager import FederationManager
from mcpgateway.types import Prompt, Resource, ServerCapabilities, Tool

# Third-Party
import pytest

# ---------------------------------------------------------------------------
# In-memory stand-ins for ORM models and SQLAlchemy Session
# ---------------------------------------------------------------------------

_id_gen = count(1)


class DummyGateway:
    def __init__(self, name, url, capabilities=None, is_active=True):
        self.id = next(_id_gen)
        self.name = name
        self.url = url
        self.capabilities = capabilities or {}
        self.is_active = is_active
        self.last_seen: datetime | None = None
        self.updated_at: datetime | None = None


class DummyTool:
    def __init__(self, name, gateway_id):
        self.id = next(_id_gen)
        self.name = name
        self.gateway_id = gateway_id
        self.is_active = True


class _ExecResult:
    """Mimic the object returned by Session.execute()."""

    def __init__(self, items=None, tools_ref=None, gateway_id=None):
        self._items = items or []
        self._tools_ref = tools_ref
        self._gateway_id = gateway_id

    class _Proxy:
        def __init__(self, items):
            self._items = items

        def all(self):
            return self._items

    def scalars(self):
        return self._Proxy(self._items)

    # Support `.delete()` for the "delete all tools for gateway_id" call
    def delete(self):
        if self._tools_ref is not None and self._gateway_id is not None:
            self._tools_ref[:] = [t for t in self._tools_ref if t.gateway_id != self._gateway_id]


class FakeSession:
    """Bare-bones Session replacement needed by FederationManager."""

    def __init__(self, gateways=None, tools=None):
        self.gateways: list[DummyGateway] = gateways or []
        self.tools: list[DummyTool] = tools or []
        self.commits = 0
        self.rollbacks = 0

    # --- ORM-ish helpers -------------------------------------------------- #

    def add(self, obj):
        # Accept any gateway-like object
        if hasattr(obj, "url") and hasattr(obj, "name"):
            self.gateways.append(obj)
        else:
            self.tools.append(obj)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, _obj):
        pass  # no-op for tests

    def get(self, _model, pk):
        """Return whatever object (Dummy or real) matches the id."""
        for g in self.gateways:
            if getattr(g, "id", None) == pk:
                return g
        return None

    def execute(self, query):
        txt = str(query).lower()
        if "tool" in txt:
            # Might be a DELETE for tools of a gateway
            if "gateway_id" in txt and "delete" in txt:
                # Extract the numeric ID at the very end of the string
                gateway_id = int(txt.split("==")[-1].strip()[:-1])
                return _ExecResult(
                    items=[t for t in self.tools if t.gateway_id == gateway_id],
                    tools_ref=self.tools,
                    gateway_id=gateway_id,
                )
            return _ExecResult(self.tools)
        # gateway SELECT
        active_gateways = [g for g in self.gateways if getattr(g, "is_active", True)]
        return _ExecResult(active_gateways)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def fed_mgr(monkeypatch):
    mgr = FederationManager()

    # Silence discovery I/O
    monkeypatch.setattr(mgr._discovery, "add_peer", lambda *a, **kw: asyncio.sleep(0))
    monkeypatch.setattr(mgr._discovery, "remove_peer", lambda *a, **kw: asyncio.sleep(0))

    # Fake gateway initialisation
    async def fake_init(url):
        assert url.startswith("http")
        return ServerCapabilities()

    monkeypatch.setattr(mgr, "_initialize_gateway", fake_init)

    yield mgr
    await mgr.stop()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_register_gateway_success(fed_mgr):
    db = FakeSession()

    gw = await fed_mgr.register_gateway(db, "http://alpha", name="Alpha")
    assert gw in db.gateways
    assert gw.url in fed_mgr._active_gateways


@pytest.mark.anyio
async def test_unregister_gateway_marks_inactive(fed_mgr):
    gw = DummyGateway("Bravo", "http://bravo")
    db = FakeSession(gateways=[gw])
    fed_mgr._active_gateways.add(gw.url)

    await fed_mgr.unregister_gateway(db, gw.id)
    assert gw.is_active is False
    assert gw.url not in fed_mgr._active_gateways


@pytest.mark.anyio
async def test_forward_request_updates_last_seen(monkeypatch, fed_mgr):
    gw = DummyGateway("Charlie", "http://charlie")

    class _FakeRsp:
        def raise_for_status(self):
            pass

        @staticmethod
        def json():
            return {"result": 42}

    async def fake_post(url, *_, **__):
        return _FakeRsp()

    monkeypatch.setattr(fed_mgr._http_client, "post", fake_post)

    result = await fed_mgr.forward_request(gw, "ping")
    assert result == 42
    assert isinstance(gw.last_seen, datetime)


@pytest.mark.anyio
async def test_get_gateway_tools(monkeypatch, fed_mgr):
    gw = DummyGateway("Delta", "http://delta")
    db = FakeSession(gateways=[gw])

    async def fake_fw(_gw, method, _params=None):
        assert method == "tools/list"
        return [{"name": "t1", "url": "http://tool"}]

    monkeypatch.setattr(fed_mgr, "forward_request", fake_fw)

    tools = await fed_mgr.get_gateway_tools(db, gw.id)
    assert tools and isinstance(tools[0], Tool) and tools[0].name == "t1"


@pytest.mark.anyio
async def test_get_gateway_resources_and_prompts(monkeypatch, fed_mgr):
    gw = DummyGateway("Echo", "http://echo")
    db = FakeSession(gateways=[gw])

    async def fake_fw(_gw, method, _params=None):
        if method == "resources/list":
            return [{"uri": "res://x", "name": "R"}]
        if method == "prompts/list":
            return [{"name": "P"}]

    monkeypatch.setattr(fed_mgr, "forward_request", fake_fw)

    resources = await fed_mgr.get_gateway_resources(db, gw.id)
    prompts = await fed_mgr.get_gateway_prompts(db, gw.id)

    assert isinstance(resources[0], Resource) and resources[0].uri == "res://x"
    assert isinstance(prompts[0], Prompt) and prompts[0].name == "P"
