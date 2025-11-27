# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_request_logging_middleware.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti
Unit tests for request logging middleware.
"""
import json
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
    body = json.dumps({"password": "123", "data": "ok"}).encode()
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
