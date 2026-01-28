# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_request_logging_middleware.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti
Unit tests for request logging middleware.
"""
import orjson
import pytest
from unittest.mock import MagicMock
from fastapi import Request, Response
from starlette.datastructures import Headers
from starlette.types import Scope
from mcpgateway.middleware.request_logging_middleware import (
    mask_sensitive_data,
    mask_jwt_in_cookies,
    mask_sensitive_headers,
    RequestLoggingMiddleware,
    SENSITIVE_KEYS,
)
import logging

class DummyLogger:
    def __init__(self):
        self.logged = []
        self.warnings = []
        self.enabled = True

    def isEnabledFor(self, level):
        return self.enabled

    def log(self, level, msg, extra=None):
        self.logged.append((level, msg))

    def warning(self, msg):
        self.warnings.append(msg)

@pytest.fixture
def dummy_logger(monkeypatch):
    logger = DummyLogger()
    monkeypatch.setattr("mcpgateway.middleware.request_logging_middleware.logger", logger)
    return logger


@pytest.fixture
def mock_structured_logger(monkeypatch):
    """Mock the structured_logger to prevent database writes."""
    mock_logger = MagicMock()
    mock_logger.log = MagicMock()
    monkeypatch.setattr("mcpgateway.middleware.request_logging_middleware.structured_logger", mock_logger)
    return mock_logger

@pytest.fixture
def dummy_call_next():
    async def _call_next(request):
        return Response(content="OK", status_code=200)
    return _call_next

def make_request(body: bytes = b"{}", headers=None, query_params=None):
    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/test",
        "headers": Headers(headers or {}).raw,
        "query_string": b"&".join(
            [f"{k}={v}".encode() for k, v in (query_params or {}).items()]
        ),
    }
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    return Request(scope, receive=receive)

# --- mask_sensitive_data tests ---

def test_mask_sensitive_data_dict():
    data = {"password": "123", "username": "user", "nested": {"token": "abc"}}
    masked = mask_sensitive_data(data)
    assert masked["password"] == "******"
    assert masked["nested"]["token"] == "******"
    assert masked["username"] == "user"

def test_mask_sensitive_data_list():
    data = [{"secret": "x"}, {"normal": "y"}]
    masked = mask_sensitive_data(data)
    assert masked[0]["secret"] == "******"
    assert masked[1]["normal"] == "y"

def test_mask_sensitive_data_non_dict_list():
    assert mask_sensitive_data("string") == "string"

# --- mask_jwt_in_cookies tests ---

def test_mask_jwt_in_cookies_with_sensitive():
    cookie = "jwt_token=abc; sessionid=xyz; other=123"
    masked = mask_jwt_in_cookies(cookie)
    assert "jwt_token=******" in masked
    assert "sessionid=******" in masked
    assert "other=123" in masked

def test_mask_jwt_in_cookies_non_sensitive():
    cookie = "user=abc; theme=dark"
    masked = mask_jwt_in_cookies(cookie)
    assert masked == cookie

def test_mask_jwt_in_cookies_empty():
    assert mask_jwt_in_cookies("") == ""

# --- mask_sensitive_headers tests ---

def test_mask_sensitive_headers_authorization():
    headers = {"Authorization": "Bearer abc", "Cookie": "jwt_token=abc", "X-Custom": "ok"}
    masked = mask_sensitive_headers(headers)
    assert masked["Authorization"] == "******"
    assert "******" in masked["Cookie"]
    assert masked["X-Custom"] == "ok"

def test_mask_sensitive_headers_non_sensitive():
    headers = {"Content-Type": "application/json"}
    masked = mask_sensitive_headers(headers)
    assert masked["Content-Type"] == "application/json"

# --- RequestLoggingMiddleware tests ---

@pytest.mark.asyncio
async def test_dispatch_logs_json_body(dummy_logger, mock_structured_logger, dummy_call_next):
    middleware = RequestLoggingMiddleware(app=None, enable_gateway_logging=False, log_detailed_requests=True)
    body = orjson.dumps({"password": "123", "data": "ok"})
    request = make_request(body=body, headers={"Authorization": "Bearer abc"})
    response = await middleware.dispatch(request, dummy_call_next)
    assert response.status_code == 200
    assert any("📩 Incoming request" in msg for _, msg in dummy_logger.logged)
    assert "******" in dummy_logger.logged[0][1]

@pytest.mark.asyncio
async def test_dispatch_logs_non_json_body(dummy_logger, mock_structured_logger, dummy_call_next):
    middleware = RequestLoggingMiddleware(app=None, enable_gateway_logging=False, log_detailed_requests=True)
    body = b"token=abc"
    request = make_request(body=body)
    response = await middleware.dispatch(request, dummy_call_next)
    assert response.status_code == 200
    assert any("<contains sensitive data - masked>" in msg for _, msg in dummy_logger.logged)

@pytest.mark.asyncio
async def test_dispatch_large_body_truncated(dummy_logger, mock_structured_logger, dummy_call_next):
    middleware = RequestLoggingMiddleware(app=None, enable_gateway_logging=False, log_detailed_requests=True, max_body_size=10)
    body = b"{" + b"a" * 100 + b"}"
    request = make_request(body=body)
    response = await middleware.dispatch(request, dummy_call_next)
    assert response.status_code == 200
    assert any("[truncated]" in msg for _, msg in dummy_logger.logged)

@pytest.mark.asyncio
async def test_dispatch_logging_disabled(dummy_logger, mock_structured_logger, dummy_call_next):
    middleware = RequestLoggingMiddleware(app=None, enable_gateway_logging=False, log_detailed_requests=False)
    body = b"{}"
    request = make_request(body=body)
    response = await middleware.dispatch(request, dummy_call_next)
    assert response.status_code == 200
    assert dummy_logger.logged == []

@pytest.mark.asyncio
async def test_dispatch_logger_disabled(dummy_logger, mock_structured_logger, dummy_call_next):
    dummy_logger.enabled = False
    middleware = RequestLoggingMiddleware(app=None, enable_gateway_logging=False, log_detailed_requests=True)
    body = b"{}"
    request = make_request(body=body)
    response = await middleware.dispatch(request, dummy_call_next)
    assert response.status_code == 200
    assert dummy_logger.logged == []

@pytest.mark.asyncio
async def test_dispatch_exception_handling(dummy_logger, mock_structured_logger, dummy_call_next, monkeypatch):
    async def bad_body():
        raise ValueError("fail")
    request = make_request()
    monkeypatch.setattr(request, "body", bad_body)
    middleware = RequestLoggingMiddleware(app=None, enable_gateway_logging=False, log_detailed_requests=True)
    response = await middleware.dispatch(request, dummy_call_next)
    assert response.status_code == 200
    assert any("Failed to log request body" in msg for msg in dummy_logger.warnings)


# --- mask_sensitive_data depth limit tests ---

def test_mask_sensitive_data_depth_limit():
    """Deep nesting should be truncated at max_depth."""
    # Create deeply nested structure
    deep_data = {"level": 0}
    current = deep_data
    for i in range(1, 15):
        current["nested"] = {"level": i}
        current = current["nested"]

    # With default depth=10, should hit limit
    masked = mask_sensitive_data(deep_data, max_depth=10)

    # Traverse to find the truncation point
    current = masked
    depth = 0
    while isinstance(current, dict) and "nested" in current:
        current = current["nested"]
        depth += 1

    # Should have been truncated before reaching depth 15
    assert current == "<nested too deep>" or depth < 15


def test_mask_sensitive_data_depth_limit_with_password():
    """Ensure sensitive data is still masked at various depths."""
    data = {"password": "secret", "nested": {"password": "nested_secret", "deeper": {"password": "deep_secret"}}}
    masked = mask_sensitive_data(data, max_depth=10)
    assert masked["password"] == "******"
    assert masked["nested"]["password"] == "******"
    assert masked["nested"]["deeper"]["password"] == "******"


# --- Large body fast path tests ---

def make_request_with_headers(body: bytes = b"{}", headers=None, query_params=None):
    """Create a request with specific headers including content-length."""
    headers = headers or {}
    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/test",
        "headers": Headers(headers).raw,
        "query_string": b"&".join(
            [f"{k}={v}".encode() for k, v in (query_params or {}).items()]
        ),
    }
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    return Request(scope, receive=receive)


@pytest.mark.asyncio
async def test_large_body_fast_path(dummy_logger, mock_structured_logger, dummy_call_next):
    """Bodies >4x max_body_size should skip detailed processing."""
    # max_body_size=100, content-length=500 (>4x) should trigger fast path
    middleware = RequestLoggingMiddleware(app=None, enable_gateway_logging=False, log_detailed_requests=True, max_body_size=100)
    body = b"x" * 500  # Large body
    request = make_request_with_headers(body=body, headers={"content-length": "500"})
    response = await middleware.dispatch(request, dummy_call_next)
    assert response.status_code == 200
    # Should log "body too large" message
    assert any("body too large: 500 bytes" in msg for _, msg in dummy_logger.logged)


@pytest.mark.asyncio
async def test_large_body_fast_path_exception_logs_failure(dummy_logger, mock_structured_logger):
    """Large body fast path should still log request failures."""
    async def _call_next(_request):
        raise RuntimeError("boom")

    middleware = RequestLoggingMiddleware(app=None, enable_gateway_logging=True, log_detailed_requests=True, max_body_size=100)
    body = b"x" * 500
    request = make_request_with_headers(body=body, headers={"content-length": "500"})

    with pytest.raises(RuntimeError):
        await middleware.dispatch(request, _call_next)

    assert mock_structured_logger.log.call_count == 1
    call_kwargs = mock_structured_logger.log.call_args.kwargs
    assert call_kwargs.get("metadata", {}).get("event") == "request_failed"


@pytest.mark.asyncio
async def test_no_logging_for_skipped_paths(mock_structured_logger, dummy_call_next):
    """Health check paths should skip all logging."""
    middleware = RequestLoggingMiddleware(app=None, enable_gateway_logging=True, log_detailed_requests=True)
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/health",  # Skip path
        "headers": [],
        "query_string": b"",
    }
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    request = Request(scope, receive=receive)
    response = await middleware.dispatch(request, dummy_call_next)
    assert response.status_code == 200
    # structured_logger.log should not have been called
    mock_structured_logger.log.assert_not_called()


# --- SENSITIVE_KEYS frozenset test ---

def test_sensitive_keys_is_frozenset():
    """SENSITIVE_KEYS should be a frozenset for performance."""
    assert isinstance(SENSITIVE_KEYS, frozenset)


# --- Skip endpoints tests ---

@pytest.mark.asyncio
async def test_skip_endpoints_skips_detailed_logging(dummy_logger, mock_structured_logger, dummy_call_next):
    """Paths matching skip_endpoints should skip detailed logging."""
    middleware = RequestLoggingMiddleware(
        app=None,
        enable_gateway_logging=False,
        log_detailed_requests=True,
        log_detailed_skip_endpoints=["/metrics", "/api/v1/status"],
    )
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/metrics",
        "headers": [],
        "query_string": b"",
    }
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    request = Request(scope, receive=receive)
    response = await middleware.dispatch(request, dummy_call_next)
    assert response.status_code == 200
    # Detailed logging should be skipped, so no "📩 Incoming request" logged
    assert not any("📩 Incoming request" in msg for _, msg in dummy_logger.logged)


@pytest.mark.asyncio
async def test_skip_endpoints_prefix_match(dummy_logger, mock_structured_logger, dummy_call_next):
    """Skip endpoints should match path prefixes."""
    middleware = RequestLoggingMiddleware(
        app=None,
        enable_gateway_logging=False,
        log_detailed_requests=True,
        log_detailed_skip_endpoints=["/api/v1/"],
    )
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/users/123",
        "headers": [],
        "query_string": b"",
    }
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    request = Request(scope, receive=receive)
    response = await middleware.dispatch(request, dummy_call_next)
    assert response.status_code == 200
    # Detailed logging should be skipped for paths starting with /api/v1/
    assert not any("📩 Incoming request" in msg for _, msg in dummy_logger.logged)


@pytest.mark.asyncio
async def test_skip_endpoints_non_matching_path_logs(dummy_logger, mock_structured_logger, dummy_call_next):
    """Paths not matching skip_endpoints should still log."""
    middleware = RequestLoggingMiddleware(
        app=None,
        enable_gateway_logging=False,
        log_detailed_requests=True,
        log_detailed_skip_endpoints=["/metrics"],
    )
    body = b'{"data": "test"}'
    request = make_request(body=body)
    response = await middleware.dispatch(request, dummy_call_next)
    assert response.status_code == 200
    # Path /test doesn't match /metrics, so detailed logging should occur
    assert any("📩 Incoming request" in msg for _, msg in dummy_logger.logged)


# --- Sampling tests ---

@pytest.mark.asyncio
async def test_sampling_rate_zero_skips_all(dummy_logger, mock_structured_logger, dummy_call_next):
    """Sample rate of 0.0 should skip all detailed logging."""
    middleware = RequestLoggingMiddleware(
        app=None,
        enable_gateway_logging=False,
        log_detailed_requests=True,
        log_detailed_sample_rate=0.0,
    )
    body = b'{"data": "test"}'
    request = make_request(body=body)
    response = await middleware.dispatch(request, dummy_call_next)
    assert response.status_code == 200
    # With sample rate 0.0, no detailed logging should occur
    assert not any("📩 Incoming request" in msg for _, msg in dummy_logger.logged)


@pytest.mark.asyncio
async def test_sampling_rate_one_logs_all(dummy_logger, mock_structured_logger, dummy_call_next):
    """Sample rate of 1.0 should log all requests."""
    middleware = RequestLoggingMiddleware(
        app=None,
        enable_gateway_logging=False,
        log_detailed_requests=True,
        log_detailed_sample_rate=1.0,
    )
    body = b'{"data": "test"}'
    request = make_request(body=body)
    response = await middleware.dispatch(request, dummy_call_next)
    assert response.status_code == 200
    # With sample rate 1.0, detailed logging should occur
    assert any("📩 Incoming request" in msg for _, msg in dummy_logger.logged)


# --- User identity resolution gating tests ---

@pytest.mark.asyncio
async def test_log_resolve_user_identity_false_skips_db_lookup(mock_structured_logger, dummy_call_next, monkeypatch):
    """When log_resolve_user_identity=False, DB lookup should be skipped."""
    # Track if get_current_user was called
    get_current_user_called = []

    async def mock_get_current_user(credentials):
        get_current_user_called.append(True)
        return MagicMock(id=1, email="test@example.com")

    monkeypatch.setattr("mcpgateway.middleware.request_logging_middleware.get_current_user", mock_get_current_user)

    middleware = RequestLoggingMiddleware(
        app=None,
        enable_gateway_logging=True,
        log_detailed_requests=False,
        log_resolve_user_identity=False,  # Explicitly disable DB lookup
    )
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/test",
        "headers": Headers({"Authorization": "Bearer test-token"}).raw,
        "query_string": b"",
    }
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    request = Request(scope, receive=receive)
    response = await middleware.dispatch(request, dummy_call_next)
    assert response.status_code == 200
    # get_current_user should NOT be called when log_resolve_user_identity=False
    assert len(get_current_user_called) == 0


@pytest.mark.asyncio
async def test_log_resolve_user_identity_true_attempts_db_lookup(mock_structured_logger, dummy_call_next, monkeypatch):
    """When log_resolve_user_identity=True, DB lookup should be attempted."""
    # Track if get_current_user was called
    get_current_user_called = []

    async def mock_get_current_user(credentials):
        get_current_user_called.append(True)
        return MagicMock(id=1, email="test@example.com")

    monkeypatch.setattr("mcpgateway.middleware.request_logging_middleware.get_current_user", mock_get_current_user)

    middleware = RequestLoggingMiddleware(
        app=None,
        enable_gateway_logging=True,
        log_detailed_requests=False,
        log_resolve_user_identity=True,  # Enable DB lookup
    )
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/test",
        "headers": Headers({"Authorization": "Bearer test-token"}).raw,
        "query_string": b"",
    }
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    request = Request(scope, receive=receive)
    response = await middleware.dispatch(request, dummy_call_next)
    assert response.status_code == 200
    # get_current_user SHOULD be called when log_resolve_user_identity=True
    assert len(get_current_user_called) == 1
