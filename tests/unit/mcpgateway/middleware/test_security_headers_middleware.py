# -*- coding: utf-8 -*-
"""Tests for the security headers middleware."""

from unittest.mock import patch

import pytest
from starlette.requests import Request
from starlette.responses import Response

from mcpgateway.middleware.security_headers import SecurityHeadersMiddleware


def _make_request(headers=None, scheme="https"):
    """Create a test request."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "scheme": scheme,
        "headers": headers or [],
    }
    return Request(scope)


async def _call_next(request):
    """Mock call_next."""
    return Response("ok")


def _mock_settings():
    """Create base mock settings."""
    mock = patch("mcpgateway.middleware.security_headers.settings")
    settings = mock.start()
    settings.security_headers_enabled = True
    settings.x_content_type_options_enabled = False
    settings.x_frame_options = None
    settings.x_xss_protection_enabled = False
    settings.x_download_options_enabled = False
    settings.hsts_enabled = False
    settings.remove_server_headers = False
    settings.environment = "production"
    settings.allowed_origins = []
    return mock, settings


@pytest.mark.asyncio
async def test_headers_disabled():
    """Test no headers when disabled."""
    mock, settings = _mock_settings()
    settings.security_headers_enabled = False
    try:
        middleware = SecurityHeadersMiddleware(app=None)
        response = await middleware.dispatch(_make_request(), _call_next)
        assert "X-Content-Type-Options" not in response.headers
    finally:
        mock.stop()


@pytest.mark.asyncio
async def test_x_content_type_options():
    """Test X-Content-Type-Options."""
    mock, settings = _mock_settings()
    settings.x_content_type_options_enabled = True
    settings.x_frame_options = "DENY"
    try:
        middleware = SecurityHeadersMiddleware(app=None)
        response = await middleware.dispatch(_make_request(), _call_next)
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
    finally:
        mock.stop()


@pytest.mark.asyncio
async def test_x_frame_options_deny():
    """Test X-Frame-Options DENY."""
    mock, settings = _mock_settings()
    settings.x_frame_options = "DENY"
    try:
        middleware = SecurityHeadersMiddleware(app=None)
        response = await middleware.dispatch(_make_request(), _call_next)
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert "frame-ancestors 'none'" in response.headers.get("Content-Security-Policy", "")
    finally:
        mock.stop()


@pytest.mark.asyncio
async def test_x_frame_options_sameorigin():
    """Test X-Frame-Options SAMEORIGIN."""
    mock, settings = _mock_settings()
    settings.x_frame_options = "SAMEORIGIN"
    try:
        middleware = SecurityHeadersMiddleware(app=None)
        response = await middleware.dispatch(_make_request(), _call_next)
        assert response.headers.get("X-Frame-Options") == "SAMEORIGIN"
        assert "frame-ancestors 'self'" in response.headers.get("Content-Security-Policy", "")
    finally:
        mock.stop()


@pytest.mark.asyncio
async def test_x_frame_options_allow_from():
    """Test X-Frame-Options ALLOW-FROM."""
    mock, settings = _mock_settings()
    settings.x_frame_options = "ALLOW-FROM https://example.com"
    try:
        middleware = SecurityHeadersMiddleware(app=None)
        response = await middleware.dispatch(_make_request(), _call_next)
        assert "frame-ancestors https://example.com" in response.headers.get("Content-Security-Policy", "")
    finally:
        mock.stop()


@pytest.mark.asyncio
async def test_x_frame_options_allow_all():
    """Test X-Frame-Options ALLOW-ALL."""
    mock, settings = _mock_settings()
    settings.x_frame_options = "ALLOW-ALL"
    try:
        middleware = SecurityHeadersMiddleware(app=None)
        response = await middleware.dispatch(_make_request(), _call_next)
        assert "frame-ancestors * file: http: https:" in response.headers.get("Content-Security-Policy", "")
    finally:
        mock.stop()


@pytest.mark.asyncio
async def test_x_frame_options_none():
    """Test X-Frame-Options None."""
    mock, settings = _mock_settings()
    settings.x_frame_options = None
    try:
        middleware = SecurityHeadersMiddleware(app=None)
        response = await middleware.dispatch(_make_request(), _call_next)
        assert "X-Frame-Options" not in response.headers
        assert "frame-ancestors" not in response.headers.get("Content-Security-Policy", "")
    finally:
        mock.stop()


@pytest.mark.asyncio
async def test_x_xss_protection():
    """Test X-XSS-Protection."""
    mock, settings = _mock_settings()
    settings.x_xss_protection_enabled = True
    try:
        middleware = SecurityHeadersMiddleware(app=None)
        response = await middleware.dispatch(_make_request(), _call_next)
        assert response.headers.get("X-XSS-Protection") == "0"
    finally:
        mock.stop()


@pytest.mark.asyncio
async def test_x_download_options():
    """Test X-Download-Options."""
    mock, settings = _mock_settings()
    settings.x_download_options_enabled = True
    try:
        middleware = SecurityHeadersMiddleware(app=None)
        response = await middleware.dispatch(_make_request(), _call_next)
        assert response.headers.get("X-Download-Options") == "noopen"
    finally:
        mock.stop()


@pytest.mark.asyncio
async def test_referrer_policy():
    """Test Referrer-Policy."""
    mock, settings = _mock_settings()
    try:
        middleware = SecurityHeadersMiddleware(app=None)
        response = await middleware.dispatch(_make_request(), _call_next)
        assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    finally:
        mock.stop()


@pytest.mark.asyncio
async def test_hsts_enabled():
    """Test HSTS."""
    mock, settings = _mock_settings()
    settings.hsts_enabled = True
    settings.hsts_max_age = 31536000
    settings.hsts_include_subdomains = True
    try:
        middleware = SecurityHeadersMiddleware(app=None)
        request = _make_request(headers=[(b"x-forwarded-proto", b"https")])
        response = await middleware.dispatch(request, _call_next)
        hsts = response.headers.get("Strict-Transport-Security")
        assert hsts is not None
        assert "max-age=31536000" in hsts
        assert "includeSubDomains" in hsts
    finally:
        mock.stop()


@pytest.mark.asyncio
async def test_cors_production_allowed():
    """Test CORS allowed."""
    mock, settings = _mock_settings()
    settings.allowed_origins = ["https://example.com"]
    settings.cors_allow_credentials = True
    try:
        middleware = SecurityHeadersMiddleware(app=None)
        request = _make_request(headers=[(b"origin", b"https://example.com")])
        response = await middleware.dispatch(request, _call_next)
        assert response.headers.get("Access-Control-Allow-Origin") == "https://example.com"
        assert response.headers.get("Access-Control-Allow-Credentials") == "true"
    finally:
        mock.stop()


@pytest.mark.asyncio
async def test_cors_production_not_allowed():
    """Test CORS not allowed."""
    mock, settings = _mock_settings()
    settings.allowed_origins = ["https://other.com"]
    try:
        middleware = SecurityHeadersMiddleware(app=None)
        request = _make_request(headers=[(b"origin", b"https://example.com")])
        response = await middleware.dispatch(request, _call_next)
        assert "Access-Control-Allow-Origin" not in response.headers
    finally:
        mock.stop()


@pytest.mark.asyncio
async def test_cors_development_all_allowed():
    """Test CORS dev mode."""
    mock, settings = _mock_settings()
    settings.environment = "development"
    settings.allowed_origins = []
    settings.cors_allow_credentials = False
    try:
        middleware = SecurityHeadersMiddleware(app=None)
        request = _make_request(headers=[(b"origin", b"https://example.com")])
        response = await middleware.dispatch(request, _call_next)
        assert response.headers.get("Access-Control-Allow-Origin") == "https://example.com"
    finally:
        mock.stop()


@pytest.mark.asyncio
async def test_remove_server_headers():
    """Test remove server headers."""

    async def call_next_with_headers(req):
        resp = Response("ok")
        resp.headers["X-Powered-By"] = "FastAPI"
        resp.headers["Server"] = "uvicorn"
        return resp

    mock, settings = _mock_settings()
    settings.remove_server_headers = True
    try:
        middleware = SecurityHeadersMiddleware(app=None)
        response = await middleware.dispatch(_make_request(), call_next_with_headers)
        assert "X-Powered-By" not in response.headers
        assert "Server" not in response.headers
    finally:
        mock.stop()


@pytest.mark.asyncio
async def test_unknown_x_frame_options():
    """Test unknown X-Frame-Options defaults to none."""
    mock, settings = _mock_settings()
    settings.x_frame_options = "UNKNOWN"
    try:
        middleware = SecurityHeadersMiddleware(app=None)
        response = await middleware.dispatch(_make_request(), _call_next)
        csp = response.headers.get("Content-Security-Policy", "")
        assert "frame-ancestors 'none'" in csp
    finally:
        mock.stop()
