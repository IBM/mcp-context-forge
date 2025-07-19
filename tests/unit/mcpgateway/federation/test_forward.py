# -*- coding: utf-8 -*-
"""Unit tests for Federation Forwarding Service.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Comprehensive unit tests for the forwarding service module with full coverage.
"""

# Standard
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway.federation.forward import ForwardingError, ForwardingService

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

    def execute(self, query):
        txt = str(query).lower()
        if "tool" in txt:
            # Handle tool queries
            for tool in self._tools:
                if hasattr(query, "whereclause") and str(query.whereclause).find(tool.name) != -1:
                    return _FakeResult(scalar=tool)
            return _FakeResult(scalar=self._tools[0] if self._tools else None)
        # Handle gateway queries
        enabled_gateways = [gw for gw in self._gateways if gw.enabled]
        return _FakeResult(scalar_list=enabled_gateways)


# ---------------------------------------------------------------------------
# ForwardingService fixture with network stubbed out
# ---------------------------------------------------------------------------


@pytest.fixture
async def fwd_service(monkeypatch):
    svc = ForwardingService()

    class _FakeResp:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self._status_code = status_code

        def raise_for_status(self):
            if self._status_code >= 400:
                raise httpx.HTTPStatusError("Error", request=None, response=self)

        def json(self):
            return self._payload

    async def fake_post(url, json=None, headers=None):
        # Default successful response
        return _FakeResp({"jsonrpc": "2.0", "id": 1, "result": {"method": json["method"]}})

    monkeypatch.setattr(svc._http_client, "post", fake_post)

    # First-Party
    from mcpgateway.config import settings

    monkeypatch.setattr(settings, "max_tool_retries", 1, raising=False)
    monkeypatch.setattr(settings, "tool_rate_limit", 10, raising=False)
    monkeypatch.setattr(settings, "basic_auth_user", "testuser", raising=False)
    monkeypatch.setattr(settings, "basic_auth_password", "testpass", raising=False)

    yield svc
    await svc.stop()


# ---------------------------------------------------------------------------
# Basic Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_init():
    """Test ForwardingService initialization."""
    service = ForwardingService()
    assert isinstance(service._http_client, httpx.AsyncClient)
    assert service._active_requests == {}
    assert service._request_history == {}
    assert service._gateway_tools == {}
    await service._http_client.aclose()


@pytest.mark.anyio
async def test_start_stop(fwd_service):
    """Test start and stop methods."""
    # Start already happened in fixture
    await fwd_service.start()  # Should work without issues

    # Add some active requests
    async def dummy_task():
        await asyncio.sleep(10)

    task = asyncio.create_task(dummy_task())
    fwd_service._active_requests["test"] = task

    # Stop should cancel active requests
    await fwd_service.stop()
    assert task.cancelled()


@pytest.mark.anyio
async def test_forwarding_error():
    """Test ForwardingError exception."""
    with pytest.raises(ForwardingError) as exc_info:
        raise ForwardingError("Test error")
    assert str(exc_info.value) == "Test error"


# ---------------------------------------------------------------------------
# forward_request Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_forward_request_targeted(fwd_service):
    """Test targeted forwarding to specific gateway."""
    gw = DummyGateway(1, "Alpha", "http://alpha")
    db = FakeSession(gateways=[gw])

    result = await fwd_service.forward_request(db, "test/method", {"param": "value"}, target_gateway_id=1)
    assert result == {"method": "test/method"}


@pytest.mark.anyio
async def test_forward_request_broadcast(fwd_service):
    """Test broadcast forwarding to all gateways."""
    gw1 = DummyGateway(1, "Alpha", "http://alpha")
    gw2 = DummyGateway(2, "Beta", "http://beta")
    db = FakeSession(gateways=[gw1, gw2])

    results = await fwd_service.forward_request(db, "tools/list")
    assert len(results) == 2
    assert all(r == {"method": "tools/list"} for r in results)


@pytest.mark.anyio
async def test_forward_request_error_handling(monkeypatch, fwd_service):
    """Test forward_request error handling."""

    async def failing_forward(*args, **kwargs):
        raise Exception("Network error")

    monkeypatch.setattr(fwd_service, "_forward_to_gateway", failing_forward)

    db = FakeSession()
    with pytest.raises(ForwardingError) as exc_info:
        await fwd_service.forward_request(db, "test", target_gateway_id=1)
    assert "Forward request failed: Network error" in str(exc_info.value)


# ---------------------------------------------------------------------------
# forward_tool_request Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_forward_tool_request_success(monkeypatch, fwd_service):
    """Test successful tool forwarding."""

    async def fake_forward(db, gid, method, params):
        assert method == "tools/invoke"
        assert params["name"] == "calculator"
        return {
            "content": [{"type": "text", "text": "Result: 42"}],
            "is_error": False,
        }

    monkeypatch.setattr(fwd_service, "_forward_to_gateway", fake_forward)

    tool = DummyTool(1, "calculator", gateway_id=42)
    db = FakeSession(gateways=[DummyGateway(42, "CalcGW", "http://calc")], tools=[tool])

    result = await fwd_service.forward_tool_request(db, "calculator", {"operation": "add", "a": 20, "b": 22})
    assert not result.is_error
    assert len(result.content) == 1
    # Access TextContent object attributes, not dictionary keys
    assert result.content[0].text == "Result: 42"
    assert result.content[0].type == "text"


@pytest.mark.anyio
async def test_forward_tool_request_not_found(fwd_service):
    """Test tool not found error."""
    db = FakeSession(tools=[])

    with pytest.raises(ForwardingError) as exc_info:
        await fwd_service.forward_tool_request(db, "unknown_tool", {})
    assert "Tool not found: unknown_tool" in str(exc_info.value)


@pytest.mark.anyio
async def test_forward_tool_request_not_federated(fwd_service):
    """Test non-federated tool error."""
    tool = DummyTool(1, "local_tool", gateway_id=None)
    db = FakeSession(tools=[tool])

    with pytest.raises(ForwardingError) as exc_info:
        await fwd_service.forward_tool_request(db, "local_tool", {})
    assert "Tool local_tool is not federated" in str(exc_info.value)


@pytest.mark.anyio
async def test_forward_tool_request_generic_error(monkeypatch, fwd_service):
    """Test generic error in tool forwarding."""
    tool = DummyTool(1, "test_tool", gateway_id=1)
    db = FakeSession(tools=[tool])

    # Make execute raise an exception
    def failing_execute(query):
        raise Exception("Database error")

    monkeypatch.setattr(db, "execute", failing_execute)

    with pytest.raises(ForwardingError) as exc_info:
        await fwd_service.forward_tool_request(db, "test_tool", {})
    assert "Failed to forward tool request: Database error" in str(exc_info.value)


# ---------------------------------------------------------------------------
# forward_resource_request Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_forward_resource_request_text(monkeypatch, fwd_service):
    """Test forwarding text resource request."""
    gateway = DummyGateway(1, "FileGW", "http://files")

    async def fake_find_gateway(db, uri):
        return gateway

    async def fake_forward(db, gid, method, params):
        assert method == "resources/read"
        assert params["uri"] == "file://hello.txt"
        return {"text": "Hello, World!", "mime_type": "text/plain"}

    monkeypatch.setattr(fwd_service, "_find_resource_gateway", fake_find_gateway)
    monkeypatch.setattr(fwd_service, "_forward_to_gateway", fake_forward)

    db = FakeSession()
    content, mime_type = await fwd_service.forward_resource_request(db, "file://hello.txt")
    assert content == "Hello, World!"
    assert mime_type == "text/plain"


@pytest.mark.anyio
async def test_forward_resource_request_binary(monkeypatch, fwd_service):
    """Test forwarding binary resource request."""
    gateway = DummyGateway(1, "FileGW", "http://files")

    async def fake_find_gateway(db, uri):
        return gateway

    async def fake_forward(db, gid, method, params):
        return {"blob": b"\x89PNG...", "mime_type": "image/png"}

    monkeypatch.setattr(fwd_service, "_find_resource_gateway", fake_find_gateway)
    monkeypatch.setattr(fwd_service, "_forward_to_gateway", fake_forward)

    db = FakeSession()
    content, mime_type = await fwd_service.forward_resource_request(db, "file://image.png")
    assert isinstance(content, bytes)
    assert content == b"\x89PNG..."
    assert mime_type == "image/png"


@pytest.mark.anyio
async def test_forward_resource_request_not_found(monkeypatch, fwd_service):
    """Test resource not found error."""

    async def fake_find_gateway(db, uri):
        return None

    monkeypatch.setattr(fwd_service, "_find_resource_gateway", fake_find_gateway)

    db = FakeSession()
    with pytest.raises(ForwardingError) as exc_info:
        await fwd_service.forward_resource_request(db, "unknown://resource")
    assert "No gateway found for resource: unknown://resource" in str(exc_info.value)


@pytest.mark.anyio
async def test_forward_resource_request_invalid_format(monkeypatch, fwd_service):
    """Test invalid resource response format."""
    gateway = DummyGateway(1, "FileGW", "http://files")

    async def fake_find_gateway(db, uri):
        return gateway

    async def fake_forward(db, gid, method, params):
        return {"invalid": "response"}

    monkeypatch.setattr(fwd_service, "_find_resource_gateway", fake_find_gateway)
    monkeypatch.setattr(fwd_service, "_forward_to_gateway", fake_forward)

    db = FakeSession()
    with pytest.raises(ForwardingError) as exc_info:
        await fwd_service.forward_resource_request(db, "file://test.txt")
    assert "Invalid resource response format" in str(exc_info.value)


@pytest.mark.anyio
async def test_forward_resource_request_generic_error(monkeypatch, fwd_service):
    """Test generic error in resource forwarding."""

    async def fake_find_gateway(db, uri):
        raise Exception("Network error")

    monkeypatch.setattr(fwd_service, "_find_resource_gateway", fake_find_gateway)

    db = FakeSession()
    with pytest.raises(ForwardingError) as exc_info:
        await fwd_service.forward_resource_request(db, "file://test.txt")
    assert "Failed to forward resource request: Network error" in str(exc_info.value)


# ---------------------------------------------------------------------------
# _forward_to_gateway Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_forward_to_gateway_success(fwd_service):
    """Test successful gateway forwarding."""
    gw = DummyGateway(1, "Alpha", "http://alpha")
    db = FakeSession(gateways=[gw])

    result = await fwd_service._forward_to_gateway(db, 1, "ping", {"x": 1})
    assert result == {"method": "ping"}
    assert isinstance(gw.last_seen, datetime)


@pytest.mark.anyio
async def test_forward_to_gateway_not_found(fwd_service):
    """Test gateway not found error."""
    db = FakeSession()

    with pytest.raises(ForwardingError) as exc_info:
        await fwd_service._forward_to_gateway(db, 999, "test")
    assert "Gateway not found: 999" in str(exc_info.value)


@pytest.mark.anyio
async def test_forward_to_gateway_disabled(fwd_service):
    """Test disabled gateway error."""
    gw = DummyGateway(1, "Alpha", "http://alpha", enabled=False)
    db = FakeSession(gateways=[gw])

    with pytest.raises(ForwardingError) as exc_info:
        await fwd_service._forward_to_gateway(db, 1, "test")
    assert "Gateway not found: 1" in str(exc_info.value)


@pytest.mark.anyio
async def test_forward_to_gateway_rate_limited(monkeypatch, fwd_service):
    """Test rate limiting."""
    gw = DummyGateway(1, "Alpha", "http://alpha")
    db = FakeSession(gateways=[gw])

    monkeypatch.setattr(fwd_service, "_check_rate_limit", lambda url: False)

    with pytest.raises(ForwardingError) as exc_info:
        await fwd_service._forward_to_gateway(db, 1, "test")
    assert "Rate limit exceeded" in str(exc_info.value)


@pytest.mark.anyio
async def test_forward_to_gateway_with_error_response(monkeypatch, fwd_service):
    """Test handling error in gateway response."""
    gw = DummyGateway(1, "Alpha", "http://alpha")
    db = FakeSession(gateways=[gw])

    async def fake_post(url, json=None, headers=None):
        class _ErrorResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"jsonrpc": "2.0", "id": 1, "error": {"message": "Method not found"}}

        return _ErrorResp()

    monkeypatch.setattr(fwd_service._http_client, "post", fake_post)

    with pytest.raises(ForwardingError) as exc_info:
        await fwd_service._forward_to_gateway(db, 1, "unknown_method")
    assert "Gateway error: Method not found" in str(exc_info.value)


@pytest.mark.anyio
async def test_forward_to_gateway_timeout_retry(monkeypatch, fwd_service):
    """Test timeout and retry logic."""
    # First-Party
    from mcpgateway.config import settings

    monkeypatch.setattr(settings, "max_tool_retries", 3, raising=False)

    gw = DummyGateway(1, "Alpha", "http://alpha")
    db = FakeSession(gateways=[gw])

    call_count = 0

    async def fake_post(url, json=None, headers=None):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise httpx.TimeoutException("Timeout")

        # Success on third attempt
        class _Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"jsonrpc": "2.0", "id": 1, "result": {"success": True}}

        return _Resp()

    monkeypatch.setattr(fwd_service._http_client, "post", fake_post)

    result = await fwd_service._forward_to_gateway(db, 1, "test")
    assert result == {"success": True}
    assert call_count == 3


@pytest.mark.anyio
async def test_forward_to_gateway_timeout_max_retries(monkeypatch, fwd_service):
    """Test timeout exceeding max retries."""
    # First-Party
    from mcpgateway.config import settings

    monkeypatch.setattr(settings, "max_tool_retries", 2, raising=False)

    gw = DummyGateway(1, "Alpha", "http://alpha")
    db = FakeSession(gateways=[gw])

    async def fake_post(url, json=None, headers=None):
        raise httpx.TimeoutException("Timeout")

    monkeypatch.setattr(fwd_service._http_client, "post", fake_post)

    with pytest.raises(ForwardingError) as exc_info:
        await fwd_service._forward_to_gateway(db, 1, "test")
    assert "Failed to forward to Alpha" in str(exc_info.value)


@pytest.mark.anyio
async def test_forward_to_gateway_generic_error(monkeypatch, fwd_service):
    """Test generic error handling."""
    gw = DummyGateway(1, "Alpha", "http://alpha")
    db = FakeSession(gateways=[gw])

    async def fake_post(url, json=None, headers=None):
        raise Exception("Connection refused")

    monkeypatch.setattr(fwd_service._http_client, "post", fake_post)

    with pytest.raises(ForwardingError) as exc_info:
        await fwd_service._forward_to_gateway(db, 1, "test")
    assert "Failed to forward to Alpha: Connection refused" in str(exc_info.value)


# ---------------------------------------------------------------------------
# _forward_to_all Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_forward_to_all_success(fwd_service):
    """Test successful broadcast to all gateways."""
    gw1 = DummyGateway(1, "Alpha", "http://alpha")
    gw2 = DummyGateway(2, "Beta", "http://beta")
    db = FakeSession(gateways=[gw1, gw2])

    results = await fwd_service._forward_to_all(db, "tools/list")
    assert len(results) == 2
    assert all(r == {"method": "tools/list"} for r in results)


@pytest.mark.anyio
async def test_forward_to_all_partial_success(monkeypatch, fwd_service):
    """Test partial success when some gateways fail."""
    gw_ok = DummyGateway(1, "GoodGW", "http://good")
    gw_bad = DummyGateway(2, "BadGW", "http://bad")

    async def fake_forward(db, gid, method, params=None):  # Add default params=None
        if gid == 1:
            return "ok!"
        raise ForwardingError("boom")

    monkeypatch.setattr(fwd_service, "_forward_to_gateway", fake_forward)

    db = FakeSession(gateways=[gw_ok, gw_bad])
    results = await fwd_service._forward_to_all(db, "stats/get")
    assert results == ["ok!"]


@pytest.mark.anyio
async def test_forward_to_all_complete_failure(monkeypatch, fwd_service):
    """Test error when all gateways fail."""
    gw1 = DummyGateway(1, "BadGW1", "http://bad1")
    gw2 = DummyGateway(2, "BadGW2", "http://bad2")

    async def fake_forward(db, gid, method, params=None):  # Add default params=None
        raise ForwardingError(f"Gateway {gid} failed")

    monkeypatch.setattr(fwd_service, "_forward_to_gateway", fake_forward)

    db = FakeSession(gateways=[gw1, gw2])
    with pytest.raises(ForwardingError) as exc_info:
        await fwd_service._forward_to_all(db, "test")
    assert "All forwards failed" in str(exc_info.value)
    assert "Gateway 1 failed" in str(exc_info.value)
    assert "Gateway 2 failed" in str(exc_info.value)


@pytest.mark.anyio
async def test_forward_to_all_no_gateways(fwd_service):
    """Test forwarding with no active gateways."""
    db = FakeSession(gateways=[])
    results = await fwd_service._forward_to_all(db, "test")
    assert results == []


# ---------------------------------------------------------------------------
# _find_resource_gateway Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_find_resource_gateway_found(monkeypatch, fwd_service):
    """Test finding gateway hosting a resource."""
    gw1 = DummyGateway(1, "Gateway 1", "http://gw1")
    gw2 = DummyGateway(2, "Gateway 2", "http://gw2")

    async def fake_forward(db, gid, method, params=None):  # Add default params=None
        assert method == "resources/list"  # This is the actual method called
        if gid == 1:
            return [{"uri": "file://doc1.txt"}, {"uri": "file://doc2.txt"}]
        else:
            return [{"uri": "file://data.csv"}, {"uri": "file://config.json"}]

    monkeypatch.setattr(fwd_service, "_forward_to_gateway", fake_forward)

    db = FakeSession(gateways=[gw1, gw2])
    gateway = await fwd_service._find_resource_gateway(db, "file://data.csv")
    assert gateway.name == "Gateway 2"


@pytest.mark.anyio
async def test_find_resource_gateway_not_found(monkeypatch, fwd_service):
    """Test resource not found in any gateway."""
    gw1 = DummyGateway(1, "Gateway 1", "http://gw1")

    async def fake_forward(db, gid, method, params=None):  # Add default params=None
        assert method == "resources/list"
        return [{"uri": "file://other.txt"}]

    monkeypatch.setattr(fwd_service, "_forward_to_gateway", fake_forward)

    db = FakeSession(gateways=[gw1])
    gateway = await fwd_service._find_resource_gateway(db, "file://missing.txt")
    assert gateway is None


@pytest.mark.anyio
async def test_find_resource_gateway_with_errors(monkeypatch, fwd_service, caplog):
    """Test finding resource with some gateway errors."""
    gw1 = DummyGateway(1, "Gateway 1", "http://gw1")
    gw2 = DummyGateway(2, "Gateway 2", "http://gw2")

    async def fake_forward(db, gid, method, params=None):  # Add default params=None
        assert method == "resources/list"
        if gid == 1:
            raise Exception("Gateway unavailable")
        else:
            return [{"uri": "file://found.txt"}]

    monkeypatch.setattr(fwd_service, "_forward_to_gateway", fake_forward)

    db = FakeSession(gateways=[gw1, gw2])
    gateway = await fwd_service._find_resource_gateway(db, "file://found.txt")
    assert gateway.name == "Gateway 2"
    assert "Failed to check gateway Gateway 1" in caplog.text


# ---------------------------------------------------------------------------
# _check_rate_limit Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_check_rate_limit_allowed():
    """Test rate limit allows requests within limit."""
    service = ForwardingService()
    url = "http://gateway1.com"

    # First few requests should be allowed
    for _ in range(5):
        assert service._check_rate_limit(url) is True

    assert len(service._request_history[url]) == 5
    await service.stop()


@pytest.mark.anyio
async def test_check_rate_limit_exceeded(monkeypatch):
    """Test rate limit exceeded."""
    # First-Party
    from mcpgateway.config import settings

    monkeypatch.setattr(settings, "tool_rate_limit", 3, raising=False)

    service = ForwardingService()
    url = "http://gateway2.com"

    # Fill up to limit
    assert service._check_rate_limit(url) is True
    assert service._check_rate_limit(url) is True
    assert service._check_rate_limit(url) is True

    # Next request should be denied
    assert service._check_rate_limit(url) is False
    await service.stop()


@pytest.mark.anyio
async def test_check_rate_limit_cleanup():
    """Test old entries cleanup in rate limiter."""
    service = ForwardingService()
    url = "http://gateway3.com"

    # Add old entries
    old_time = datetime.now(timezone.utc) - timedelta(seconds=61)
    recent_time = datetime.now(timezone.utc) - timedelta(seconds=30)
    service._request_history[url] = [old_time, old_time, recent_time]

    # Check should clean old entries
    assert service._check_rate_limit(url) is True

    # Should have recent + new entry only
    assert len(service._request_history[url]) == 2
    await service.stop()


@pytest.mark.anyio
async def test_check_rate_limit_multiple_gateways():
    """Test rate limiting is per-gateway URL."""
    service = ForwardingService()

    # Different gateways should have separate limits
    assert service._check_rate_limit("http://gateway1.com") is True
    assert service._check_rate_limit("http://gateway2.com") is True
    assert service._check_rate_limit("http://gateway1.com") is True

    assert len(service._request_history["http://gateway1.com"]) == 2
    assert len(service._request_history["http://gateway2.com"]) == 1
    await service.stop()


# ---------------------------------------------------------------------------
# _get_auth_headers Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_auth_headers():
    """Test authentication header generation."""
    service = ForwardingService()

    with patch("mcpgateway.config.settings.basic_auth_user", "testuser"):
        with patch("mcpgateway.config.settings.basic_auth_password", "testpass"):
            headers = service._get_auth_headers()

    assert headers["Authorization"] == "Basic testuser:testpass"
    assert headers["X-API-Key"] == "testuser:testpass"
    assert len(headers) == 2
    await service.stop()


@pytest.mark.anyio
async def test_get_auth_headers_different_creds():
    """Test auth headers with different credentials."""
    service = ForwardingService()

    with patch("mcpgateway.config.settings.basic_auth_user", "admin"):
        with patch("mcpgateway.config.settings.basic_auth_password", "secret123"):
            headers = service._get_auth_headers()

    assert headers["Authorization"] == "Basic admin:secret123"
    assert headers["X-API-Key"] == "admin:secret123"
    await service.stop()


# ---------------------------------------------------------------------------
# Edge Cases and Integration Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_forward_with_no_params(fwd_service):
    """Test forwarding without parameters."""
    gw = DummyGateway(1, "Alpha", "http://alpha")
    db = FakeSession(gateways=[gw])

    result = await fwd_service._forward_to_gateway(db, 1, "status")
    assert result == {"method": "status"}


@pytest.mark.anyio
async def test_concurrent_forwards(monkeypatch, fwd_service):
    """Test concurrent forwarding to multiple gateways."""
    gateways = [DummyGateway(i, f"Gateway{i}", f"http://gw{i}") for i in range(1, 6)]

    call_times = []

    async def fake_forward(db, gid, method, params=None):  # Add default params=None
        start = asyncio.get_event_loop().time()
        await asyncio.sleep(0.1)  # Simulate network delay
        call_times.append((gid, asyncio.get_event_loop().time() - start))
        return {"gateway_id": gid, "status": "ok"}

    monkeypatch.setattr(fwd_service, "_forward_to_gateway", fake_forward)

    db = FakeSession(gateways=gateways)
    results = await fwd_service._forward_to_all(db, "health/check")

    # All gateways should respond
    assert len(results) == 5

    # Verify they ran concurrently (total time should be ~0.1s, not 0.5s)
    assert all(0.09 < duration < 0.15 for _, duration in call_times)


@pytest.mark.anyio
async def test_forward_tool_with_empty_content(monkeypatch, fwd_service):
    """Test tool forwarding with empty content."""

    async def fake_forward(db, gid, method, params):
        return {"content": [], "is_error": False}

    monkeypatch.setattr(fwd_service, "_forward_to_gateway", fake_forward)

    tool = DummyTool(1, "empty_tool", gateway_id=1)
    db = FakeSession(gateways=[DummyGateway(1, "GW", "http://gw")], tools=[tool])

    result = await fwd_service.forward_tool_request(db, "empty_tool", {})
    assert not result.is_error
    assert result.content == []


@pytest.mark.anyio
async def test_forward_resource_with_defaults(monkeypatch, fwd_service):
    """Test resource forwarding with default MIME types."""
    gateway = DummyGateway(1, "FileGW", "http://files")

    async def fake_find_gateway(db, uri):
        return gateway

    async def fake_forward_text(db, gid, method, params):
        return {"text": "Plain text"}  # No mime_type specified

    monkeypatch.setattr(fwd_service, "_find_resource_gateway", fake_find_gateway)
    monkeypatch.setattr(fwd_service, "_forward_to_gateway", fake_forward_text)

    db = FakeSession()
    content, mime_type = await fwd_service.forward_resource_request(db, "file://plain.txt")
    assert content == "Plain text"
    assert mime_type == "text/plain"  # Default

    # Test binary with default
    async def fake_forward_binary(db, gid, method, params):
        return {"blob": b"binary data"}  # No mime_type specified

    monkeypatch.setattr(fwd_service, "_forward_to_gateway", fake_forward_binary)

    content, mime_type = await fwd_service.forward_resource_request(db, "file://data.bin")
    assert content == b"binary data"
    assert mime_type == "application/octet-stream"  # Default
