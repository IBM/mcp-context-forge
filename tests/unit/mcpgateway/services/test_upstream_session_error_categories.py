# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_upstream_session_error_categories.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Tests for upstream session error categorization and diagnostics (observability enhancement).

This test suite validates that the enhanced error handling in upstream_session_registry.py
correctly unwraps ExceptionGroup instances and categorizes different failure modes, making
it easy for operators to distinguish between:
- Connection failures (refused, reset)
- Timeouts
- SSL/TLS issues
- Authentication errors (401, 403)
- DNS resolution failures
- Upstream server errors (5xx)
"""

# Standard
import asyncio
import ssl

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway.services.upstream_session_registry import (
    SessionCreateRequest,
    TransportType,
)


def _make_request(**overrides):
    """Helper to create a SessionCreateRequest with defaults."""
    defaults = {
        "url": "https://upstream.example.com/mcp",
        "transport_type": TransportType.STREAMABLE_HTTP,
        "headers": {},
        "gateway_id": "test-gateway",
        "downstream_session_id": "test-session",
        "httpx_client_factory": None,
        "message_handler_factory": None,
        "timeout_seconds": 5.0,
    }
    defaults.update(overrides)
    return SessionCreateRequest(**defaults)


class _FakeTransportCtx:
    """Fake transport context manager that raises on enter."""

    def __init__(self, enter_exc=None):
        self._enter_exc = enter_exc

    async def __aenter__(self):
        if self._enter_exc is not None:
            raise self._enter_exc
        return ("read_stream", "write_stream", object())

    async def __aexit__(self, *_exc_info):
        pass


class _FakeClientSessionCM:
    """Fake ClientSession context manager."""

    def __init__(self, *_args, **_kwargs):
        self.initialized = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info):
        pass

    async def initialize(self):
        self.initialized = True


@pytest.mark.asyncio
async def test_connection_refused_error_category(monkeypatch):
    """ConnectionRefusedError should be categorized as 'connection_refused'."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    def fake_stream(**_kw):
        return _FakeTransportCtx(enter_exc=ConnectionRefusedError("Connection refused"))

    monkeypatch.setattr(usr, "streamablehttp_client", fake_stream)
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    req = _make_request()
    with pytest.raises(RuntimeError) as exc_info:
        await usr._default_session_factory(req)  # pylint: disable=protected-access

    error_msg = str(exc_info.value)
    assert "[connection_refused]" in error_msg
    assert "ConnectionRefusedError" in error_msg


@pytest.mark.asyncio
async def test_timeout_error_category(monkeypatch):
    """TimeoutError should be categorized as 'timeout'."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    def fake_stream(**_kw):
        return _FakeTransportCtx(enter_exc=asyncio.TimeoutError("Connection timeout"))

    monkeypatch.setattr(usr, "streamablehttp_client", fake_stream)
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    req = _make_request()
    with pytest.raises(RuntimeError) as exc_info:
        await usr._default_session_factory(req)  # pylint: disable=protected-access

    error_msg = str(exc_info.value)
    assert "[timeout]" in error_msg
    assert "TimeoutError" in error_msg


@pytest.mark.asyncio
async def test_ssl_error_category(monkeypatch):
    """SSL errors should be categorized as 'ssl_tls'."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    def fake_stream(**_kw):
        return _FakeTransportCtx(enter_exc=ssl.SSLError("certificate verify failed"))

    monkeypatch.setattr(usr, "streamablehttp_client", fake_stream)
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    req = _make_request()
    with pytest.raises(RuntimeError) as exc_info:
        await usr._default_session_factory(req)  # pylint: disable=protected-access

    error_msg = str(exc_info.value)
    assert "[ssl_tls]" in error_msg
    assert "SSLError" in error_msg or "certificate" in error_msg.lower()


@pytest.mark.asyncio
async def test_http_401_auth_error_category(monkeypatch):
    """HTTP 401 should be categorized as 'auth_unauthorized'."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    # Create a fake 401 response
    request = httpx.Request("GET", "https://upstream.example.com/mcp")
    response = httpx.Response(401, request=request)
    http_error = httpx.HTTPStatusError("Unauthorized", request=request, response=response)

    def fake_stream(**_kw):
        return _FakeTransportCtx(enter_exc=http_error)

    monkeypatch.setattr(usr, "streamablehttp_client", fake_stream)
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    req = _make_request()
    with pytest.raises(RuntimeError) as exc_info:
        await usr._default_session_factory(req)  # pylint: disable=protected-access

    error_msg = str(exc_info.value)
    assert "[auth_unauthorized]" in error_msg
    assert "HTTPStatusError" in error_msg


@pytest.mark.asyncio
async def test_http_403_auth_error_category(monkeypatch):
    """HTTP 403 should be categorized as 'auth_forbidden'."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    request = httpx.Request("GET", "https://upstream.example.com/mcp")
    response = httpx.Response(403, request=request)
    http_error = httpx.HTTPStatusError("Forbidden", request=request, response=response)

    def fake_stream(**_kw):
        return _FakeTransportCtx(enter_exc=http_error)

    monkeypatch.setattr(usr, "streamablehttp_client", fake_stream)
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    req = _make_request()
    with pytest.raises(RuntimeError) as exc_info:
        await usr._default_session_factory(req)  # pylint: disable=protected-access

    error_msg = str(exc_info.value)
    assert "[auth_forbidden]" in error_msg
    assert "HTTPStatusError" in error_msg


@pytest.mark.asyncio
async def test_http_500_server_error_category(monkeypatch):
    """HTTP 500 should be categorized as 'upstream_server_error'."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    request = httpx.Request("GET", "https://upstream.example.com/mcp")
    response = httpx.Response(500, request=request)
    http_error = httpx.HTTPStatusError("Internal Server Error", request=request, response=response)

    def fake_stream(**_kw):
        return _FakeTransportCtx(enter_exc=http_error)

    monkeypatch.setattr(usr, "streamablehttp_client", fake_stream)
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    req = _make_request()
    with pytest.raises(RuntimeError) as exc_info:
        await usr._default_session_factory(req)  # pylint: disable=protected-access

    error_msg = str(exc_info.value)
    assert "[upstream_server_error]" in error_msg
    assert "HTTPStatusError" in error_msg


@pytest.mark.asyncio
async def test_dns_resolution_error_category(monkeypatch):
    """DNS resolution failures should be categorized as 'dns_resolution'."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    def fake_stream(**_kw):
        return _FakeTransportCtx(enter_exc=OSError("[Errno -2] Name or service not known"))

    monkeypatch.setattr(usr, "streamablehttp_client", fake_stream)
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    req = _make_request()
    with pytest.raises(RuntimeError) as exc_info:
        await usr._default_session_factory(req)  # pylint: disable=protected-access

    error_msg = str(exc_info.value)
    assert "[dns_resolution]" in error_msg
    assert "OSError" in error_msg


@pytest.mark.asyncio
async def test_connection_reset_error_category(monkeypatch):
    """Connection reset errors should be categorized as 'connection_reset'."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    def fake_stream(**_kw):
        return _FakeTransportCtx(enter_exc=OSError("[Errno 54] Connection reset by peer"))

    monkeypatch.setattr(usr, "streamablehttp_client", fake_stream)
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    req = _make_request()
    with pytest.raises(RuntimeError) as exc_info:
        await usr._default_session_factory(req)  # pylint: disable=protected-access

    error_msg = str(exc_info.value)
    assert "[connection_reset]" in error_msg
    assert "OSError" in error_msg


@pytest.mark.asyncio
async def test_httpx_connect_error_category(monkeypatch):
    """httpx.ConnectError should be categorized as 'connection_error'."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    def fake_stream(**_kw):
        return _FakeTransportCtx(enter_exc=httpx.ConnectError("Failed to connect"))

    monkeypatch.setattr(usr, "streamablehttp_client", fake_stream)
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    req = _make_request()
    with pytest.raises(RuntimeError) as exc_info:
        await usr._default_session_factory(req)  # pylint: disable=protected-access

    error_msg = str(exc_info.value)
    assert "[connection_error]" in error_msg
    assert "ConnectError" in error_msg


@pytest.mark.asyncio
async def test_exception_group_unwrapping(monkeypatch):
    """ExceptionGroup should be unwrapped to show the root cause."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    # Create a nested ExceptionGroup like MCP SDK does
    root_error = ConnectionRefusedError("Connection refused by upstream")
    inner_group = ExceptionGroup("inner task group", [root_error])
    outer_group = ExceptionGroup("unhandled errors in a TaskGroup (1 sub-exception)", [inner_group])

    def fake_stream(**_kw):
        return _FakeTransportCtx(enter_exc=outer_group)

    monkeypatch.setattr(usr, "streamablehttp_client", fake_stream)
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    req = _make_request()
    with pytest.raises(RuntimeError) as exc_info:
        await usr._default_session_factory(req)  # pylint: disable=protected-access

    error_msg = str(exc_info.value)
    # Should NOT contain the generic TaskGroup message
    assert "unhandled errors in a TaskGroup" not in error_msg
    # Should contain the actual root cause
    assert "[connection_refused]" in error_msg
    assert "ConnectionRefusedError" in error_msg
    assert "Connection refused by upstream" in error_msg
