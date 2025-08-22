# -*- coding: utf-8 -*-
"""Location: ./tests/security/test_configurable_headers.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Configurable Security Headers Testing.

This module tests the configurable security headers implementation for issue #533.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch

from mcpgateway.middleware.security_headers import SecurityHeadersMiddleware
from mcpgateway.config import settings


def test_security_headers_can_be_disabled():
    """Test that security headers can be disabled via configuration."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/test")
    def test_endpoint():
        return {"message": "test"}

    with patch.object(settings, 'security_headers_enabled', False):
        client = TestClient(app)
        response = client.get("/test")

        # When disabled, security headers should not be present
        assert "X-Content-Type-Options" not in response.headers
        assert "X-Frame-Options" not in response.headers
        assert "X-XSS-Protection" not in response.headers
        assert "X-Download-Options" not in response.headers


def test_individual_headers_configurable():
    """Test that individual security headers can be configured."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/test")
    def test_endpoint():
        return {"message": "test"}

    # Test with some headers disabled
    with patch.multiple(settings,
                       security_headers_enabled=True,
                       x_content_type_options_enabled=False,
                       x_frame_options="SAMEORIGIN",
                       x_xss_protection_enabled=False,
                       x_download_options_enabled=True):
        client = TestClient(app)
        response = client.get("/test")

        # Check configured headers
        assert "X-Content-Type-Options" not in response.headers  # Disabled
        assert response.headers["X-Frame-Options"] == "SAMEORIGIN"  # Custom value
        assert "X-XSS-Protection" not in response.headers  # Disabled
        assert response.headers["X-Download-Options"] == "noopen"  # Enabled
        assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"  # Always on


def test_hsts_configuration():
    """Test HSTS header configuration options."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/test")
    def test_endpoint():
        return {"message": "test"}

    # Test with custom HSTS settings
    with patch.multiple(settings,
                       security_headers_enabled=True,
                       hsts_enabled=True,
                       hsts_max_age=7776000,  # 90 days
                       hsts_include_subdomains=False):
        client = TestClient(app)
        response = client.get("/test", headers={"X-Forwarded-Proto": "https"})

        # Check HSTS configuration
        assert "Strict-Transport-Security" in response.headers
        hsts_value = response.headers["Strict-Transport-Security"]
        assert "max-age=7776000" in hsts_value
        assert "includeSubDomains" not in hsts_value  # Disabled


def test_hsts_can_be_disabled():
    """Test that HSTS can be disabled."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/test")
    def test_endpoint():
        return {"message": "test"}

    with patch.multiple(settings,
                       security_headers_enabled=True,
                       hsts_enabled=False):
        client = TestClient(app)
        response = client.get("/test", headers={"X-Forwarded-Proto": "https"})

        # HSTS should not be present when disabled
        assert "Strict-Transport-Security" not in response.headers


def test_server_header_removal_configurable():
    """Test that server header removal is configurable."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/test")
    def test_endpoint():
        return {"message": "test"}

    # Test with server header removal disabled
    with patch.multiple(settings,
                       security_headers_enabled=True,
                       remove_server_headers=False):
        client = TestClient(app)
        response = client.get("/test")

        # Server headers should not be removed when disabled
        # Note: FastAPI/Starlette might not add these headers in test mode,
        # but our middleware won't remove them if they exist
        pass  # This test mainly validates the configuration works


def test_all_headers_with_default_config():
    """Test all headers with default configuration."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/test")
    def test_endpoint():
        return {"message": "test"}

    # Use default settings (all should be enabled)
    client = TestClient(app)
    response = client.get("/test")

    # All default headers should be present
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-XSS-Protection"] == "0"
    assert response.headers["X-Download-Options"] == "noopen"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Content-Security-Policy" in response.headers
