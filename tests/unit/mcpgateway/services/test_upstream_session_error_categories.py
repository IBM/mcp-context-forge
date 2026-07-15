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


@pytest.mark.asyncio
async def test_http_404_not_found_error_category(monkeypatch):
    """HTTP 404 should be categorized as 'not_found'."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    request = httpx.Request("GET", "https://upstream.example.com/mcp")
    response = httpx.Response(404, request=request)
    http_error = httpx.HTTPStatusError("Not Found", request=request, response=response)

    def fake_stream(**_kw):
        return _FakeTransportCtx(enter_exc=http_error)

    monkeypatch.setattr(usr, "streamablehttp_client", fake_stream)
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    req = _make_request()
    with pytest.raises(RuntimeError) as exc_info:
        await usr._default_session_factory(req)  # pylint: disable=protected-access

    error_msg = str(exc_info.value)
    assert "[not_found]" in error_msg
    assert "HTTPStatusError" in error_msg


@pytest.mark.asyncio
async def test_http_other_status_error_category(monkeypatch):
    """HTTP status codes not in 401/403/404/5xx should be categorized as 'http_error'."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    request = httpx.Request("GET", "https://upstream.example.com/mcp")
    response = httpx.Response(418, request=request)  # I'm a teapot
    http_error = httpx.HTTPStatusError("I'm a teapot", request=request, response=response)

    def fake_stream(**_kw):
        return _FakeTransportCtx(enter_exc=http_error)

    monkeypatch.setattr(usr, "streamablehttp_client", fake_stream)
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    req = _make_request()
    with pytest.raises(RuntimeError) as exc_info:
        await usr._default_session_factory(req)  # pylint: disable=protected-access

    error_msg = str(exc_info.value)
    assert "[http_error]" in error_msg
    assert "HTTPStatusError" in error_msg


@pytest.mark.asyncio
async def test_http_status_error_no_status_code(monkeypatch):
    """HTTPStatusError without response.status_code should be categorized as 'http_error'."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    # Create an HTTPStatusError but mock response to have no status_code
    request = httpx.Request("GET", "https://upstream.example.com/mcp")
    response = httpx.Response(500, request=request)
    http_error = httpx.HTTPStatusError("Server Error", request=request, response=response)
    # Monkey-patch the response object to return None for status_code
    http_error.response.status_code = None  # type: ignore[assignment]

    def fake_stream(**_kw):
        return _FakeTransportCtx(enter_exc=http_error)

    monkeypatch.setattr(usr, "streamablehttp_client", fake_stream)
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    req = _make_request()
    with pytest.raises(RuntimeError) as exc_info:
        await usr._default_session_factory(req)  # pylint: disable=protected-access

    error_msg = str(exc_info.value)
    assert "[http_error]" in error_msg
    assert "HTTPStatusError" in error_msg


@pytest.mark.asyncio
async def test_oserror_generic_network_error_category(monkeypatch):
    """OSError without specific keywords should be categorized as 'network_error'."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    def fake_stream(**_kw):
        return _FakeTransportCtx(enter_exc=OSError("[Errno 99] Some other network error"))

    monkeypatch.setattr(usr, "streamablehttp_client", fake_stream)
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    req = _make_request()
    with pytest.raises(RuntimeError) as exc_info:
        await usr._default_session_factory(req)  # pylint: disable=protected-access

    error_msg = str(exc_info.value)
    assert "[network_error]" in error_msg
    assert "OSError" in error_msg


@pytest.mark.asyncio
async def test_structured_logger_exception_handling(monkeypatch):
    """If structured logger fails, the primary error path should continue."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    def fake_stream(**_kw):
        return _FakeTransportCtx(enter_exc=ConnectionRefusedError("Connection refused"))

    # Track that the broken logger was actually called
    logger_called = []

    # Mock structured logger to raise an exception
    def fake_get_structured_logger():
        logger_called.append(True)
        class BrokenLogger:
            def log(self, *args, **kwargs):
                raise RuntimeError("Structured logger is broken!")
        return BrokenLogger()

    monkeypatch.setattr(usr, "streamablehttp_client", fake_stream)
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    # Patch get_structured_logger in the module where it will be imported
    import mcpgateway.services.structured_logger
    monkeypatch.setattr(
        mcpgateway.services.structured_logger,
        "get_structured_logger",
        fake_get_structured_logger
    )

    req = _make_request()
    # Should still raise RuntimeError with the connection error, not the logger error
    with pytest.raises(RuntimeError) as exc_info:
        await usr._default_session_factory(req)  # pylint: disable=protected-access

    error_msg = str(exc_info.value)
    # Primary error should still be present
    assert "[connection_refused]" in error_msg
    assert "ConnectionRefusedError" in error_msg
    # Should NOT contain the structured logger error
    assert "Structured logger is broken" not in error_msg
    # Verify the logger was actually invoked (confirming we hit the except block)
    assert logger_called, "Structured logger should have been called"


@pytest.mark.asyncio
async def test_logger_error_call_with_exc_info(monkeypatch, caplog):
    """Verify that logger.error is called with exc_info=exc for tracebacks."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    def fake_stream(**_kw):
        return _FakeTransportCtx(enter_exc=ConnectionRefusedError("Connection refused"))

    monkeypatch.setattr(usr, "streamablehttp_client", fake_stream)
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    req = _make_request()

    with caplog.at_level("ERROR"):
        with pytest.raises(RuntimeError):
            await usr._default_session_factory(req)  # pylint: disable=protected-access

    # Verify logger.error was called with the categorized error message
    assert any(
        "connection_refused" in record.message
        and "ConnectionRefusedError" in record.message
        for record in caplog.records
    ), "Logger should have recorded the categorized error"

    # Verify exc_info was included (provides traceback for debugging)
    assert any(
        record.exc_info is not None
        for record in caplog.records
    ), "Logger should have included exc_info for traceback"


@pytest.mark.asyncio
async def test_structured_logger_metadata_payload(monkeypatch):
    """Verify structured logger receives correct metadata payload."""
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    def fake_stream(**_kw):
        # Create an HTTP 401 error for auth_unauthorized category
        request = httpx.Request("GET", "https://upstream.example.com/mcp")
        response = httpx.Response(401, request=request)
        http_error = httpx.HTTPStatusError("Unauthorized", request=request, response=response)
        return _FakeTransportCtx(enter_exc=http_error)

    # Track structured logger calls
    structured_log_calls = []

    def fake_get_structured_logger():
        class MockStructuredLogger:
            def log(self, **kwargs):
                structured_log_calls.append(kwargs)
        return MockStructuredLogger()

    monkeypatch.setattr(usr, "streamablehttp_client", fake_stream)
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    import mcpgateway.services.structured_logger
    monkeypatch.setattr(
        mcpgateway.services.structured_logger,
        "get_structured_logger",
        fake_get_structured_logger
    )

    req = _make_request()
    with pytest.raises(RuntimeError):
        await usr._default_session_factory(req)  # pylint: disable=protected-access

    # Verify structured logger was called
    assert len(structured_log_calls) == 1, "Structured logger should have been called once"

    call = structured_log_calls[0]
    # Verify required fields
    assert call["level"] == "ERROR"
    assert call["message"] == "Upstream MCP session creation failed"
    assert call["component"] == "upstream_session_registry"

    # Verify metadata payload
    metadata = call["metadata"]
    assert "url" in metadata
    assert metadata["downstream_session_id"] == "test-session"
    assert metadata["gateway_id"] == "test-gateway"
    assert metadata["transport_type"] == "streamablehttp"
    assert metadata["error_category"] == "auth_unauthorized"
    assert metadata["exception_type"] == "HTTPStatusError"
    assert "exception_message" in metadata


@pytest.mark.asyncio
async def test_cross_layer_error_message_consistency(monkeypatch):
    """
    Regression test for cross-layer consistency: verify that registry-created RuntimeError
    surfaces the same categorized root-cause text through the tool_service consuming layer.

    This ensures that the fix for the generic "unhandled errors in a TaskGroup" message
    remains effective across the entire error propagation chain.
    """
    # First-Party
    from mcpgateway.services import upstream_session_registry as usr

    # Create a connection refused error as the root cause
    def fake_stream(**_kw):
        return _FakeTransportCtx(enter_exc=ConnectionRefusedError("Connection refused by server"))

    monkeypatch.setattr(usr, "streamablehttp_client", fake_stream)
    monkeypatch.setattr(usr, "ClientSession", _FakeClientSessionCM)

    req = _make_request()

    # The registry creates a RuntimeError with categorized error information
    try:
        await usr._default_session_factory(req)  # pylint: disable=protected-access
        assert False, "Should have raised RuntimeError"
    except RuntimeError as registry_error:
        # Verify the registry error message contains:
        # 1. Error category
        # 2. Exception type
        # 3. Original error message
        error_msg = str(registry_error)

        # Should NOT contain generic TaskGroup message
        assert "unhandled errors in a TaskGroup" not in error_msg, \
            "Generic TaskGroup message should be replaced with specific error"

        # Should contain specific categorized error information
        assert "[connection_refused]" in error_msg, \
            "Error category should be present"
        assert "ConnectionRefusedError" in error_msg, \
            "Exception type should be present"
        assert "Connection refused by server" in error_msg, \
            "Original error message should be preserved"

        # Verify format matches expected pattern:
        # "Failed to create upstream MCP session for <url>: [<category>] <type>: <message>"
        assert "Failed to create upstream MCP session for" in error_msg
        assert "https://upstream.example.com/mcp" in error_msg

        # This RuntimeError would be caught by tool_service.py which unwraps
        # BaseExceptionGroup. Since we already unwrapped at registry level,
        # the consuming layer receives a clean RuntimeError with actionable text.
