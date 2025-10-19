# -*- coding: utf-8 -*-
"""Location: ./tests/security/test_standalone_middleware.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Standalone Security Middleware Testing.

This module tests the security middleware in isolation without the full app.
"""

# Standard

# Third-Party
from fastapi import FastAPI
from fastapi.testclient import TestClient

# First-Party
from mcpgateway.middleware.security_headers import SecurityHeadersMiddleware


def test_security_headers_middleware_basic():
    """Test security headers middleware in isolation."""
    # Create a minimal FastAPI app
    app = FastAPI()

    # Add the security headers middleware
    app.add_middleware(SecurityHeadersMiddleware)

    # Add a simple endpoint
    @app.get("/test")
    def test_endpoint():
        return {"message": "test"}

    # Create test client
    client = TestClient(app)

    # Make request
    response = client.get("/test")

    # Check that security headers are present
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-XSS-Protection"] == "0"
    assert response.headers["X-Download-Options"] == "noopen"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Content-Security-Policy" in response.headers

    # Check that sensitive headers are removed
    assert "X-Powered-By" not in response.headers
    assert "Server" not in response.headers


def test_security_headers_hsts_on_https():
    """Test HSTS header is added for HTTPS requests."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/test")
    def test_endpoint():
        return {"message": "test"}

    client = TestClient(app)

    # Make request with HTTPS indication
    response = client.get("/test", headers={"X-Forwarded-Proto": "https"})

    # Check HSTS header
    assert "Strict-Transport-Security" in response.headers
    assert "max-age=31536000" in response.headers["Strict-Transport-Security"]
    assert "includeSubDomains" in response.headers["Strict-Transport-Security"]


def test_security_headers_no_hsts_on_http():
    """Test HSTS header is not added for HTTP requests."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/test")
    def test_endpoint():
        return {"message": "test"}

    client = TestClient(app)

    # Make regular HTTP request
    response = client.get("/test")

    # Check HSTS header is not present
    assert "Strict-Transport-Security" not in response.headers


def test_csp_header_structure():
    """Test CSP header has correct structure."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/test")
    def test_endpoint():
        return {"message": "test"}

    client = TestClient(app)
    response = client.get("/test")

    csp = response.headers["Content-Security-Policy"]

    # Check for essential CSP directives
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp
    assert "img-src 'self'" in csp
    assert "font-src 'self'" in csp
    assert "connect-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp

    # Check that required CDN domains are allowed for Admin UI
    assert "https://cdnjs.cloudflare.com" in csp
    assert "https://cdn.tailwindcss.com" in csp
    assert "https://cdn.jsdelivr.net" in csp

    # Verify CSP ends with semicolon
    assert csp.endswith(";")
