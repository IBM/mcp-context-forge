# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/middleware/test_security_headers_middleware.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for the security headers middleware.
"""

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
async def test_x_frame_options_raw_empty_string():
    """Test that raw empty string (bypassing config validator) is treated as None."""
    mock, settings = _mock_settings()
    settings.x_frame_options = ""
    try:
        middleware = SecurityHeadersMiddleware(app=None)
        response = await middleware.dispatch(_make_request(), _call_next)
        assert "X-Frame-Options" not in response.headers
        assert "frame-ancestors" not in response.headers.get("Content-Security-Policy", "")
    finally:
        mock.stop()


@pytest.mark.asyncio
async def test_x_frame_options_raw_whitespace_string():
    """Test that raw whitespace string (bypassing config validator) is treated as None."""
    mock, settings = _mock_settings()
    settings.x_frame_options = "   "
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


@pytest.mark.asyncio
async def test_root_path_is_stripped_from_path_for_csp_skip_check():
    mock, settings = _mock_settings()
    try:
        middleware = SecurityHeadersMiddleware(app=None)
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/app/docs",
                "root_path": "/app",
                "scheme": "https",
                "headers": [],
            }
        )

        response = await middleware.dispatch(request, _call_next)

        assert response.status_code == 200
    finally:
        mock.stop()


@pytest.mark.asyncio
async def test_sse_streaming_preserves_no_cache_header():
    """Test that SSE streaming endpoints preserve Cache-Control: no-cache."""

    async def call_next_sse(req):
        """Mock call_next that returns an SSE streaming response."""
        resp = Response("data: test\n\n", media_type="text/event-stream")
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    mock, settings = _mock_settings()
    try:
        middleware = SecurityHeadersMiddleware(app=None)
        # Use a protected path that would normally get no-store, private
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/a2a/test-agent/stream",
                "scheme": "https",
                "headers": [],
            }
        )

        response = await middleware.dispatch(request, call_next_sse)

        # SSE endpoints should preserve no-cache, not get no-store, private
        assert response.headers.get("Cache-Control") == "no-cache"
        assert "no-store" not in response.headers.get("Cache-Control", "")
        assert "private" not in response.headers.get("Cache-Control", "")
        # Should still have security headers
        assert response.headers.get("Pragma") == "no-cache"
        assert response.headers.get("Expires") == "0"
        assert "Authorization" in response.headers.get("Vary", "")
    finally:
        mock.stop()


@pytest.mark.asyncio
async def test_sse_streaming_adds_no_cache_if_missing():
    """Test that SSE streaming endpoints get no-cache added if not present."""

    async def call_next_sse_no_cache(req):
        """Mock call_next that returns an SSE streaming response without Cache-Control."""
        resp = Response("data: test\n\n", media_type="text/event-stream")
        # Intentionally omit Cache-Control header
        return resp

    mock, settings = _mock_settings()
    try:
        middleware = SecurityHeadersMiddleware(app=None)
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/a2a/test-agent/stream",
                "scheme": "https",
                "headers": [],
            }
        )

        response = await middleware.dispatch(request, call_next_sse_no_cache)

        # SSE endpoints should get no-cache added
        assert response.headers.get("Cache-Control") == "no-cache"
    finally:
        mock.stop()


@pytest.mark.asyncio
async def test_non_sse_protected_path_gets_no_store_private():
    """Test that non-SSE protected endpoints get Cache-Control: no-store, private."""

    async def call_next_api(req):
        """Mock call_next that returns a regular API response."""
        resp = Response('{"status": "ok"}', media_type="application/json")
        return resp

    mock, settings = _mock_settings()
    try:
        middleware = SecurityHeadersMiddleware(app=None)
        # Use a protected path
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/a2a/agents",
                "scheme": "https",
                "headers": [],
            }
        )

        response = await middleware.dispatch(request, call_next_api)

        # Non-SSE protected endpoints should get no-store, private
        assert response.headers.get("Cache-Control") == "no-store, private"
        assert response.headers.get("Pragma") == "no-cache"
        assert response.headers.get("Expires") == "0"
        assert "Authorization" in response.headers.get("Vary", "")
    finally:
        mock.stop()


@pytest.mark.asyncio
async def test_exempted_path_no_cache_control_override():
    """Test that exempted paths don't get cache control headers."""

    async def call_next_static(req):
        """Mock call_next that returns a static file response."""
        resp = Response("static content", media_type="text/plain")
        return resp

    mock, settings = _mock_settings()
    try:
        middleware = SecurityHeadersMiddleware(app=None)
        # Use an exempted path (static files)
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/static/app.js",
                "scheme": "https",
                "headers": [],
            }
        )

        response = await middleware.dispatch(request, call_next_static)

        # Exempted paths should not get cache control headers added
        assert "Cache-Control" not in response.headers
        assert "Pragma" not in response.headers
        assert "Expires" not in response.headers
    finally:
        mock.stop()


@pytest.mark.asyncio
async def test_sse_content_type_with_charset():
    """Test that SSE detection works with charset in Content-Type."""

    async def call_next_sse_charset(req):
        """Mock call_next that returns an SSE response with charset."""
        resp = Response("data: test\n\n", media_type="text/event-stream; charset=utf-8")
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    mock, settings = _mock_settings()
    try:
        middleware = SecurityHeadersMiddleware(app=None)
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/a2a/test-agent/stream",
                "scheme": "https",
                "headers": [],
            }
        )

        response = await middleware.dispatch(request, call_next_sse_charset)

        # Should still detect SSE and preserve no-cache
        assert "text/event-stream" in response.headers.get("content-type", "")
        assert response.headers.get("Cache-Control") == "no-cache"
    finally:
        mock.stop()


@pytest.mark.asyncio
async def test_non_sse_with_no_cache_gets_overridden():
    """Test that non-SSE endpoints with no-cache get it overridden to no-store, private."""

    async def call_next_api_with_no_cache(req):
        """Mock call_next that returns a regular API response with no-cache."""
        resp = Response('{"status": "ok"}', media_type="application/json")
        resp.headers["Cache-Control"] = "no-cache"  # Will be overridden
        return resp

    mock, settings = _mock_settings()
    try:
        middleware = SecurityHeadersMiddleware(app=None)
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/a2a/agents",
                "scheme": "https",
                "headers": [],
            }
        )

        response = await middleware.dispatch(request, call_next_api_with_no_cache)

        # Non-SSE protected endpoints should have no-cache overridden
        assert response.headers.get("Cache-Control") == "no-store, private"
    finally:
        mock.stop()


@pytest.mark.asyncio
async def test_sse_vary_authorization_header_added():
    """Test that SSE endpoints get Vary: Authorization header added."""

    async def call_next_sse_no_vary(req):
        """Mock call_next that returns an SSE response without Vary header."""
        resp = Response("data: test\n\n", media_type="text/event-stream")
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    mock, settings = _mock_settings()
    try:
        middleware = SecurityHeadersMiddleware(app=None)
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/a2a/test-agent/stream",
                "scheme": "https",
                "headers": [],
            }
        )

        response = await middleware.dispatch(request, call_next_sse_no_vary)

        # Should have Vary: Authorization added
        assert "Authorization" in response.headers.get("Vary", "")
    finally:
        mock.stop()


@pytest.mark.asyncio
async def test_sse_vary_authorization_preserves_existing_vary():
    """Test that SSE endpoints preserve existing Vary headers and add Authorization."""

    async def call_next_sse_with_vary(req):
        """Mock call_next that returns an SSE response with existing Vary header."""
        resp = Response("data: test\n\n", media_type="text/event-stream")
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["Vary"] = "Accept-Encoding, Origin"
        return resp

    mock, settings = _mock_settings()
    try:
        middleware = SecurityHeadersMiddleware(app=None)
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/a2a/test-agent/stream",
                "scheme": "https",
                "headers": [],
            }
        )

        response = await middleware.dispatch(request, call_next_sse_with_vary)

        # Should have Authorization added to existing Vary headers
        vary_header = response.headers.get("Vary", "")
        assert "Authorization" in vary_header
        assert "Accept-Encoding" in vary_header
        assert "Origin" in vary_header
    finally:
        mock.stop()
