# -*- coding: utf-8 -*-
"""Unit tests for Federation Forwarding Service.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Comprehensive unit tests for the forwarding service module.
"""

# Standard
from datetime import datetime

# Third-Party
import pytest

# First-Party
from mcpgateway.federation.forward import ForwardingError, ForwardingService, ToolResult
from mcpgateway.models import TextContent

# ---------------------------------------------------------------------------
# Tiny dummy ORM objects + fake Session
# ---------------------------------------------------------------------------


class DummyGateway:
    def __init__(self, id_, name, url, enabled: bool = True, reachable: bool = True):
        self.id = id_
        self.name = name
        self.url = url
        self.enabled = enabled
        self.reachable = reachable
        self.last_seen: datetime | None = None


class DummyTool:
    def __init__(self, id_, name, gateway_id=None, enabled: bool = True, reachable: bool = True):
        self.id = id_
        self.name = name
        self.gateway_id = gateway_id
        self.enabled = enabled
        self.reachable = reachable


class _FakeResult:
    def __init__(self, scalar=None, scalar_list=None):
        self._scalar = scalar
        self._scalar_list = scalar_list or []

    def scalar_one_or_none(self):
        return self._scalar

    class _Proxy:
        def __init__(self, items):
            self._items = items

        def all(self):
            return self._items

    def scalars(self):
        return self._Proxy(self._scalar_list)


class FakeSession:
    def __init__(self, gateways=None, tools=None):
        self._gateways = gateways or []
        self._tools = tools or []

    def get(self, _model, pk):
        for gw in self._gateways:
            if gw.id == pk:
                return gw
        return None

    def execute(self, query):  # pragma: no cover
        txt = str(query).lower()
        if "tool" in txt:
            return _FakeResult(scalar=self._tools[0] if self._tools else None)
        return _FakeResult(scalar_list=self._gateways)


# ---------------------------------------------------------------------------
# ForwardingService fixture with network stubbed out
# ---------------------------------------------------------------------------


@pytest.fixture
async def fwd_service(monkeypatch):
    svc = ForwardingService()

    class _FakeResp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    async def fake_post(url, json=None, headers=None):  # noqa: D401
        return _FakeResp({"result": {"method": json["method"]}})

    monkeypatch.setattr(svc._http_client, "post", fake_post)

    # First-Party
    from mcpgateway.config import settings

    monkeypatch.setattr(settings, "max_tool_retries", 1, raising=False)
    yield svc
    await svc.stop()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_forward_to_gateway_success(fwd_service):
    gw = DummyGateway(1, "Alpha", "http://alpha")
    db = FakeSession(gateways=[gw])

    result = await fwd_service._forward_to_gateway(db, 1, "ping", {"x": 1})
    assert result == {"method": "ping"}
    assert isinstance(gw.last_seen, datetime)


@pytest.mark.anyio
async def test_forward_tool_request_parses_result(monkeypatch, fwd_service):
    # Fake gateway call to produce valid ContentType payload
    async def fake_forward(db, gid, method, params):  # noqa: D401
        assert method == "tools/invoke"
        payload = {
            "content": [TextContent(type="text", text="OK").model_dump()],
            "is_error": False,
        }
        return payload

    monkeypatch.setattr(fwd_service, "_forward_to_gateway", fake_forward)  # type: ignore[arg-type]

    tool = DummyTool(1, "echo", gateway_id=42)
    db = FakeSession(gateways=[DummyGateway(42, "EchoGW", "http://echo")], tools=[tool])

    result: ToolResult = await fwd_service.forward_tool_request(db, "echo", {"msg": "hi"})
    assert result.is_error is False
    assert isinstance(result.content[0], TextContent) and result.content[0].text == "OK"


@pytest.mark.anyio
async def test_rate_limit(monkeypatch):
    # First-Party
    from mcpgateway.config import settings

    monkeypatch.setattr(settings, "tool_rate_limit", 2, raising=False)

    svc = ForwardingService()
    url = "http://beta"
    assert svc._check_rate_limit(url)
    assert svc._check_rate_limit(url)
    assert svc._check_rate_limit(url) is False  # third call exceeds limit


@pytest.mark.anyio
async def test_forward_to_all_partial_success(monkeypatch, fwd_service):
    gw_ok = DummyGateway(1, "GoodGW", "http://good")
    gw_bad = DummyGateway(2, "BadGW", "http://bad")

    async def fake_forward(db, gid, method, params):  # noqa: D401
        if gid == 1:
            return "ok!"
        raise ForwardingError("boom")

    monkeypatch.setattr(fwd_service, "_forward_to_gateway", fake_forward)  # type: ignore[arg-type]

    db = FakeSession(gateways=[gw_ok, gw_bad])
    results = await fwd_service._forward_to_all(db, "stats/get")
    assert results == ["ok!"]
