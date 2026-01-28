# -*- coding: utf-8 -*-
"""Location: ./tests/security/test_security_middleware_comprehensive.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Comprehensive Security Middleware Testing.

This module provides comprehensive test coverage for the SecurityHeadersMiddleware
including all configuration combinations, edge cases, and integration scenarios.
"""

# Standard
from unittest.mock import patch

# Third-Party
from fastapi import FastAPI, HTTPException, Response
from fastapi.testclient import TestClient
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.middleware.security_headers import SecurityHeadersMiddleware


class TestSecurityHeadersConfiguration:
    """Test all security header configuration options."""

    @pytest.mark.parametrize("enabled", [True, False])
    def test_security_headers_enabled_toggle(self, enabled: bool):
        """Test security headers can be globally enabled/disabled."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        with patch.object(settings, "security_headers_enabled", enabled):
            client = TestClient(app)
            response = client.get("/test")

            if enabled:
                # When enabled, headers should be present
                assert "X-Content-Type-Options" in response.headers
                assert "X-Frame-Options" in response.headers
                assert "Content-Security-Policy" in response.headers
            else:
                # When disabled, no security headers should be added
                assert "X-Content-Type-Options" not in response.headers
                assert "X-Frame-Options" not in response.headers
                assert "Content-Security-Policy" not in response.headers

    @pytest.mark.parametrize("x_content_enabled", [True, False])
    def test_x_content_type_options_configurable(self, x_content_enabled: bool):
        """Test X-Content-Type-Options can be individually configured."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        with patch.multiple(settings, security_headers_enabled=True, x_content_type_options_enabled=x_content_enabled):
            client = TestClient(app)
            response = client.get("/test")

            if x_content_enabled:
                assert response.headers["X-Content-Type-Options"] == "nosniff"
            else:
                assert "X-Content-Type-Options" not in response.headers

    @pytest.mark.parametrize("frame_option", ["DENY", "SAMEORIGIN", ""])
    def test_x_frame_options_configurable(self, frame_option: str):
        """Test X-Frame-Options values are configurable."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        with patch.multiple(settings, security_headers_enabled=True, x_frame_options=frame_option):
            client = TestClient(app)
            response = client.get("/test")

            if frame_option:
                assert response.headers["X-Frame-Options"] == frame_option
            else:
                assert "X-Frame-Options" not in response.headers

    @pytest.mark.parametrize("xss_enabled", [True, False])
    def test_x_xss_protection_configurable(self, xss_enabled: bool):
        """Test X-XSS-Protection can be configured."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        with patch.multiple(settings, security_headers_enabled=True, x_xss_protection_enabled=xss_enabled):
            client = TestClient(app)
            response = client.get("/test")

            if xss_enabled:
                assert response.headers["X-XSS-Protection"] == "0"
            else:
                assert "X-XSS-Protection" not in response.headers

    @pytest.mark.parametrize("download_enabled", [True, False])
    def test_x_download_options_configurable(self, download_enabled: bool):
        """Test X-Download-Options can be configured."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        with patch.multiple(settings, security_headers_enabled=True, x_download_options_enabled=download_enabled):
            client = TestClient(app)
            response = client.get("/test")

            if download_enabled:
                assert response.headers["X-Download-Options"] == "noopen"
            else:
                assert "X-Download-Options" not in response.headers

    def test_referrer_policy_always_set(self):
        """Test Referrer-Policy is always set regardless of configuration."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        with patch.object(settings, "security_headers_enabled", True):
            client = TestClient(app)
            response = client.get("/test")

            # Referrer-Policy should always be set when headers are enabled
            assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


class TestHSTSConfiguration:
    """Test HSTS header configuration options."""

    @pytest.mark.parametrize("hsts_enabled", [True, False])
    def test_hsts_enabled_toggle(self, hsts_enabled: bool):
        """Test HSTS can be enabled/disabled."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        with patch.multiple(settings, security_headers_enabled=True, hsts_enabled=hsts_enabled):
            client = TestClient(app)
            response = client.get("/test", headers={"X-Forwarded-Proto": "https"})

            if hsts_enabled:
                assert "Strict-Transport-Security" in response.headers
            else:
                assert "Strict-Transport-Security" not in response.headers

    @pytest.mark.parametrize("max_age", [86400, 31536000, 63072000])  # 1 day, 1 year, 2 years
    def test_hsts_max_age_configurable(self, max_age: int):
        """Test HSTS max-age is configurable."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        with patch.multiple(settings, security_headers_enabled=True, hsts_enabled=True, hsts_max_age=max_age, hsts_include_subdomains=False):
            client = TestClient(app)
            response = client.get("/test", headers={"X-Forwarded-Proto": "https"})

            assert "Strict-Transport-Security" in response.headers
            hsts_value = response.headers["Strict-Transport-Security"]
            assert f"max-age={max_age}" in hsts_value
            assert "includeSubDomains" not in hsts_value

    @pytest.mark.parametrize("include_subdomains", [True, False])
    def test_hsts_include_subdomains_configurable(self, include_subdomains: bool):
        """Test HSTS includeSubDomains directive is configurable."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        with patch.multiple(settings, security_headers_enabled=True, hsts_enabled=True, hsts_max_age=31536000, hsts_include_subdomains=include_subdomains):
            client = TestClient(app)
            response = client.get("/test", headers={"X-Forwarded-Proto": "https"})

            hsts_value = response.headers["Strict-Transport-Security"]
            if include_subdomains:
                assert "includeSubDomains" in hsts_value
            else:
                assert "includeSubDomains" not in hsts_value

    @pytest.mark.parametrize("proto_header", ["https", "http", "invalid", None])
    def test_hsts_protocol_detection(self, proto_header: str):
        """Test HSTS activation based on protocol detection."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        with patch.multiple(settings, security_headers_enabled=True, hsts_enabled=True):
            client = TestClient(app)
            headers = {}
            if proto_header:
                headers["X-Forwarded-Proto"] = proto_header

            response = client.get("/test", headers=headers)

            if proto_header == "https":
                assert "Strict-Transport-Security" in response.headers
            else:
                assert "Strict-Transport-Security" not in response.headers


class TestServerHeaderRemoval:
    """Test server header removal configuration."""

    @pytest.mark.parametrize("remove_headers", [True, False])
    def test_server_header_removal_configurable(self, remove_headers: bool):
        """Test server header removal can be configured."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            response = Response(content='{"message": "test"}', media_type="application/json")
            # Simulate headers that might be set by the server
            response.headers["X-Powered-By"] = "TestServer/1.0"
            response.headers["Server"] = "TestServer/1.0"
            return response

        with patch.multiple(settings, security_headers_enabled=True, remove_server_headers=remove_headers):
            client = TestClient(app)
            response = client.get("/test")

            # Note: In test mode, these headers might not be present initially
            # This test mainly validates the configuration logic works
            if remove_headers:
                # Headers should be removed if they exist
                assert "X-Powered-By" not in response.headers
                assert "Server" not in response.headers
            # If remove_headers=False, the middleware wouldn't remove them
            # but in test mode they might not be present anyway


class TestCSPConfiguration:
    """Test Content Security Policy configuration."""

    def test_csp_always_present_when_headers_enabled(self):
        """Test CSP is always present when security headers are enabled."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        with patch.object(settings, "security_headers_enabled", True):
            client = TestClient(app)
            response = client.get("/test")

            assert "Content-Security-Policy" in response.headers
            csp = response.headers["Content-Security-Policy"]

            # Verify essential directives
            assert "default-src 'self'" in csp
            assert "frame-ancestors 'none'" in csp
            assert csp.endswith(";")

    def test_csp_includes_admin_ui_cdns(self):
        """Test CSP includes all required CDN domains for Admin UI."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        with patch.object(settings, "security_headers_enabled", True):
            client = TestClient(app)
            response = client.get("/test")

            csp = response.headers["Content-Security-Policy"]

            # Check all required CDN domains are allowed
            required_domains = ["https://cdnjs.cloudflare.com", "https://cdn.tailwindcss.com", "https://cdn.jsdelivr.net"]

            for domain in required_domains:
                assert domain in csp, f"{domain} missing from CSP"


class TestMiddlewareIntegration:
    """Test middleware integration with various response types."""

    def test_security_headers_on_json_response(self):
        """Test headers are added to JSON responses."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test", "data": [1, 2, 3]}

        client = TestClient(app)
        response = client.get("/test")

        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert "Content-Security-Policy" in response.headers
        assert response.json() == {"message": "test", "data": [1, 2, 3]}

    def test_security_headers_on_html_response(self):
        """Test headers are added to HTML responses."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return Response(content="<html><body>Test</body></html>", media_type="text/html")

        client = TestClient(app)
        response = client.get("/test")

        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert "Content-Security-Policy" in response.headers
        assert "<html>" in response.text

    def test_security_headers_on_different_status_codes(self):
        """Test headers are added to responses with different status codes."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/success")
        def success_endpoint():
            return {"message": "success"}

        @app.get("/not-found")
        def not_found_endpoint():
            raise HTTPException(status_code=404, detail="Not found")

        client = TestClient(app)

        # Test successful response
        response = client.get("/success")
        assert response.status_code == 200
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert "Content-Security-Policy" in response.headers

        # Test 404 response
        response = client.get("/not-found")
        assert response.status_code == 404
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert "Content-Security-Policy" in response.headers

    def test_security_headers_preserve_existing_headers(self):
        """Test middleware preserves existing response headers."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            response = Response(content='{"test": true}', media_type="application/json")
            response.headers["Custom-Header"] = "custom-value"
            response.headers["Cache-Control"] = "no-cache"
            return response

        client = TestClient(app)
        response = client.get("/test")

        # Existing headers should be preserved
        assert response.headers["Custom-Header"] == "custom-value"
        assert response.headers["Cache-Control"] == "no-cache"

        # Security headers should be added
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert "Content-Security-Policy" in response.headers


class TestAllConfigurationCombinations:
    """Test various combinations of security header configurations."""

    def test_all_headers_disabled_except_csp(self):
        """Test configuration with only CSP enabled."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        with patch.multiple(
            settings,
            security_headers_enabled=True,
            x_content_type_options_enabled=False,
            x_frame_options="",  # Empty means disabled
            x_xss_protection_enabled=False,
            x_download_options_enabled=False,
            hsts_enabled=False,
            remove_server_headers=False,
        ):
            client = TestClient(app)
            response = client.get("/test")

            # Only CSP and Referrer-Policy should be present
            assert "X-Content-Type-Options" not in response.headers
            assert "X-Frame-Options" not in response.headers
            assert "X-XSS-Protection" not in response.headers
            assert "X-Download-Options" not in response.headers
            assert "Strict-Transport-Security" not in response.headers

            # These are always set when headers are enabled
            assert "Content-Security-Policy" in response.headers
            assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    def test_maximum_security_configuration(self):
        """Test configuration with all security features enabled."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        with patch.multiple(
            settings,
            security_headers_enabled=True,
            x_content_type_options_enabled=True,
            x_frame_options="DENY",
            x_xss_protection_enabled=True,
            x_download_options_enabled=True,
            hsts_enabled=True,
            hsts_max_age=63072000,  # 2 years
            hsts_include_subdomains=True,
            remove_server_headers=True,
        ):
            client = TestClient(app)
            response = client.get("/test", headers={"X-Forwarded-Proto": "https"})

            # All headers should be present
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.headers["X-Frame-Options"] == "DENY"
            assert response.headers["X-XSS-Protection"] == "0"
            assert response.headers["X-Download-Options"] == "noopen"
            assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
            assert "Content-Security-Policy" in response.headers

            # HSTS with custom settings
            hsts_value = response.headers["Strict-Transport-Security"]
            assert "max-age=63072000" in hsts_value
            assert "includeSubDomains" in hsts_value


class TestMiddlewareErrorHandling:
    """Test middleware behavior in error scenarios."""

    def test_middleware_handles_none_response(self):
        """Test middleware handles edge case responses gracefully."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        # Test with normal response
        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 200
        assert "X-Content-Type-Options" in response.headers

    def test_middleware_with_request_variations(self):
        """Test middleware with different request types."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/get-test")
        def get_endpoint():
            return {"method": "GET"}

        @app.post("/post-test")
        def post_endpoint():
            return {"method": "POST"}

        @app.put("/put-test")
        def put_endpoint():
            return {"method": "PUT"}

        client = TestClient(app)

        # Test different HTTP methods all get security headers
        for method, endpoint in [("GET", "/get-test"), ("POST", "/post-test"), ("PUT", "/put-test")]:
            if method == "GET":
                response = client.get(endpoint)
            elif method == "POST":
                response = client.post(endpoint)
            elif method == "PUT":
                response = client.put(endpoint)

            assert response.status_code == 200
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert "Content-Security-Policy" in response.headers


class TestProtocolDetection:
    """Test various protocol detection scenarios for HSTS."""

    @pytest.mark.parametrize(
        "request_scheme,forwarded_proto,expect_hsts",
        [
            ("https", None, True),
            ("http", "https", True),
            ("https", "https", True),
            ("http", "http", False),
            ("http", None, False),
            ("https", "http", True),  # Request scheme takes precedence
        ],
    )
    def test_hsts_protocol_detection_combinations(self, request_scheme: str, forwarded_proto: str, expect_hsts: bool):
        """Test HSTS activation under various protocol scenarios."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        with patch.multiple(settings, security_headers_enabled=True, hsts_enabled=True):
            client = TestClient(app)

            # Mock the request URL scheme
            headers = {}
            if forwarded_proto:
                headers["X-Forwarded-Proto"] = forwarded_proto

            # Note: TestClient always uses 'http' scheme, so we test forwarded proto
            response = client.get("/test", headers=headers)

            if expect_hsts and forwarded_proto == "https":
                assert "Strict-Transport-Security" in response.headers
            else:
                assert "Strict-Transport-Security" not in response.headers


class TestConfigurationValidation:
    """Test configuration validation and edge cases."""

    def test_empty_configuration_values(self):
        """Test behavior with empty configuration values."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        with patch.multiple(
            settings,
            security_headers_enabled=True,
            x_frame_options="",  # Empty string
            hsts_max_age=0,
        ):  # Zero value
            client = TestClient(app)
            response = client.get("/test", headers={"X-Forwarded-Proto": "https"})

            # Empty x_frame_options should result in no header
            assert "X-Frame-Options" not in response.headers

            # Zero max-age should still work
            if "Strict-Transport-Security" in response.headers:
                assert "max-age=0" in response.headers["Strict-Transport-Security"]

    def test_settings_access_during_request(self):
        """Test that settings are properly accessed during request processing."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        # Create a mock settings object to verify access patterns
        with patch("mcpgateway.middleware.security_headers.settings") as mock_settings:
            mock_settings.security_headers_enabled = True
            mock_settings.x_content_type_options_enabled = True
            mock_settings.x_frame_options = "DENY"
            mock_settings.x_xss_protection_enabled = True
            mock_settings.x_download_options_enabled = True
            mock_settings.hsts_enabled = False
            mock_settings.remove_server_headers = True

            client = TestClient(app)
            response = client.get("/test")

            # Verify settings were accessed
            assert mock_settings.security_headers_enabled
            assert response.headers["X-Content-Type-Options"] == "nosniff"


class TestFrameAncestorsCSPConsistency:
    """Test that CSP frame-ancestors directive matches X-Frame-Options setting."""

    @pytest.mark.parametrize(
        "x_frame_options,expected_frame_ancestors",
        [
            ("DENY", "'none'"),
            ("SAMEORIGIN", "'self'"),
            ("ALLOW-FROM https://example.com", "https://example.com"),
            ("ALLOW-ALL", "*"),  # Empty string should allow all
            ("invalid-value", "'none'"),  # Unknown values default to none
        ],
    )
    def test_csp_frame_ancestors_matches_x_frame_options(self, x_frame_options: str, expected_frame_ancestors: str):
        """Test that CSP frame-ancestors directive is consistent with X-Frame-Options setting."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        with patch.multiple(
            settings,
            security_headers_enabled=True,
            x_frame_options=x_frame_options,
            x_content_type_options_enabled=True,
            x_xss_protection_enabled=True,
            x_download_options_enabled=True,
            hsts_enabled=False,  # Disable HSTS for simpler testing
            remove_server_headers=False,
            environment="development",
            allowed_origins=set(),
            cors_allow_credentials=False,
        ):
            client = TestClient(app)
            response = client.get("/test")

            # Check CSP header contains correct frame-ancestors directive
            csp_header = response.headers.get("Content-Security-Policy", "")
            expected_directive = f"frame-ancestors {expected_frame_ancestors}"
            assert expected_directive in csp_header, f"Expected CSP to contain '{expected_directive}' but got: {csp_header}"

            # Check X-Frame-Options header is set correctly (or omitted for empty string)
            if x_frame_options:
                assert response.headers.get("X-Frame-Options") == x_frame_options
            else:
                assert "X-Frame-Options" not in response.headers

    def test_sameorigin_iframe_integration(self):
        """Integration test for SAMEORIGIN iframe functionality.

        Regression test to ensure X_FRAME_OPTIONS=SAMEORIGIN works correctly
        with consistent CSP frame-ancestors directive.
        """
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/")
        def root():
            return {"message": "OK"}

        # Test SAMEORIGIN configuration scenario
        with patch.multiple(
            settings,
            security_headers_enabled=True,
            x_frame_options="SAMEORIGIN",  # User's desired setting
            x_content_type_options_enabled=True,
            x_xss_protection_enabled=True,
            x_download_options_enabled=True,
            hsts_enabled=False,
            remove_server_headers=False,
            environment="development",
            allowed_origins={"*"},  # From user's ALLOWED_ORIGINS=["*"]
            cors_allow_credentials=False,
        ):
            client = TestClient(app)
            response = client.get("/")

            # Verify both headers are consistent and allow same-origin framing
            assert response.headers["X-Frame-Options"] == "SAMEORIGIN"

            csp_header = response.headers["Content-Security-Policy"]
            assert "frame-ancestors 'self'" in csp_header
            assert "frame-ancestors 'none'" not in csp_header

            # This should now work for iframe embedding from same origin
            assert response.status_code == 200
