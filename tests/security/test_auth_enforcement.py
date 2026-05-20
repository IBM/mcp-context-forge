"""
Authentication enforcement and security header tests for MCP Gateway.
Extends existing test coverage with additional edge cases for issue #259.

Run:
    pytest tests/security/test_auth_enforcement.py -v

Environment variables:
    GATEWAY_URL    Base URL (default: http://localhost:4444)
    ADMIN_TOKEN    Bearer token for admin user
"""
from __future__ import annotations

import os
import ssl
import urllib.request

import pytest
import requests

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:4444").rstrip("/")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
TIMEOUT = 10


def url(path: str) -> str:
    return f"{GATEWAY_URL}/{path.lstrip('/')}"


class TestSecurityHeaders:
    @pytest.fixture(scope="class")
    def health_response(self):
        return requests.get(url("/health"), timeout=TIMEOUT)

    def test_x_content_type_options(self, health_response):
        value = health_response.headers.get("X-Content-Type-Options", "")
        assert value.lower() == "nosniff", f"Got: {value!r}"

    def test_x_frame_options(self, health_response):
        value = health_response.headers.get("X-Frame-Options", "")
        assert value.upper() in ("DENY", "SAMEORIGIN"), f"Got: {value!r}"

    def test_content_security_policy_present(self, health_response):
        assert "Content-Security-Policy" in health_response.headers

    def test_no_server_header_information_disclosure(self, health_response):
        server = health_response.headers.get("Server", "")
        sensitive = ("uvicorn", "python", "werkzeug", "gunicorn", "nginx/", "apache/")
        assert not any(t in server.lower() for t in sensitive), f"Server header leaks: {server!r}"

    def test_no_x_powered_by(self, health_response):
        assert "X-Powered-By" not in health_response.headers


class TestAuthenticationEnforcement:
    PROTECTED_ENDPOINTS = [
        "/admin/tools", "/admin/servers", "/admin/gateways",
        "/admin/users", "/v1/tools", "/v1/resources",
    ]

    @pytest.mark.parametrize("endpoint", PROTECTED_ENDPOINTS)
    def test_unauthenticated_returns_401(self, endpoint):
        resp = requests.get(url(endpoint), timeout=TIMEOUT)
        assert resp.status_code == 401, f"Expected 401 on {endpoint}, got {resp.status_code}"

    @pytest.mark.parametrize("endpoint", PROTECTED_ENDPOINTS)
    def test_invalid_token_returns_401(self, endpoint):
        resp = requests.get(
            url(endpoint),
            headers={"Authorization": "Bearer invalid.token.here"},
            timeout=TIMEOUT,
        )
        assert resp.status_code == 401, f"Expected 401 on {endpoint}, got {resp.status_code}"

    @pytest.mark.skipif(not ADMIN_TOKEN, reason="ADMIN_TOKEN not set")
    @pytest.mark.parametrize("endpoint", ["/admin/tools", "/v1/tools"])
    def test_valid_token_returns_2xx(self, endpoint):
        resp = requests.get(
            url(endpoint),
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
            timeout=TIMEOUT,
        )
        assert 200 <= resp.status_code < 300, f"Got {resp.status_code} on {endpoint}"

    def test_options_preflight_not_401(self):
        resp = requests.options(
            url("/v1/tools"),
            headers={"Origin": "https://example.com", "Access-Control-Request-Method": "GET"},
            timeout=TIMEOUT,
        )
        assert resp.status_code in (200, 204), f"CORS preflight returned {resp.status_code}"


class TestAdminAccessControl:
    ADMIN_ONLY = ["/admin/users", "/admin/gateways"]

    @pytest.mark.parametrize("endpoint", ADMIN_ONLY)
    def test_admin_endpoint_rejects_no_credentials(self, endpoint):
        resp = requests.get(url(endpoint), timeout=TIMEOUT)
        assert resp.status_code in (401, 403), f"Got {resp.status_code} on {endpoint}"


class TestTLSConfiguration:
    @pytest.mark.skipif(
        not GATEWAY_URL.startswith("https://"),
        reason="TLS tests only run against HTTPS endpoints",
    )
    def test_tls_certificate_valid(self):
        resp = requests.get(url("/health"), verify=True, timeout=TIMEOUT)
        assert resp.status_code == 200

    @pytest.mark.skipif(
        not GATEWAY_URL.startswith("https://"),
        reason="TLS tests only run against HTTPS endpoints",
    )
    def test_tls_minimum_version(self):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_default_certs()
        req = urllib.request.Request(url("/health"))
        with urllib.request.urlopen(req, context=ctx, timeout=TIMEOUT) as resp:
            assert resp.status == 200
