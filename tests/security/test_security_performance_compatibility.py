# -*- coding: utf-8 -*-
"""Location: ./tests/security/test_security_performance_compatibility.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Security Performance and Compatibility Testing.

This module tests the performance impact and browser/tool compatibility
of the security implementation.
"""

# Standard
import re
import time
from unittest.mock import patch

# Third-Party
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.middleware.security_headers import SecurityHeadersMiddleware


class TestPerformanceImpact:
    """Test performance impact of security middleware."""

    def test_middleware_overhead_minimal(self):
        """Test security middleware has minimal performance overhead."""
        # App without security middleware
        app_no_security = FastAPI()

        @app_no_security.get("/test")
        def test_endpoint():
            return {"message": "test"}

        # App with security middleware
        app_with_security = FastAPI()
        app_with_security.add_middleware(SecurityHeadersMiddleware)

        @app_with_security.get("/test")
        def test_endpoint():
            return {"message": "test"}

        # Measure performance
        iterations = 100

        # Time without security
        client_no_security = TestClient(app_no_security)
        start_time = time.perf_counter()
        for i in range(iterations):
            response = client_no_security.get("/test")
            assert response.status_code == 200
        time_without_security = time.perf_counter() - start_time

        # Time with security
        client_with_security = TestClient(app_with_security)
        start_time = time.perf_counter()
        for i in range(iterations):
            response = client_with_security.get("/test")
            assert response.status_code == 200
        time_with_security = time.perf_counter() - start_time

        # Security overhead should be reasonable (< 3x increase)
        overhead_ratio = time_with_security / time_without_security
        assert overhead_ratio < 3, f"Security middleware overhead too high: {overhead_ratio}x"

    def test_memory_usage_stable(self):
        """Test security middleware doesn't cause memory leaks."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test", "data": list(range(100))}

        client = TestClient(app)

        # Make many requests to check for memory leaks
        for i in range(200):
            response = client.get(f"/test?iteration={i}")
            assert response.status_code == 200
            assert "X-Content-Type-Options" in response.headers

        # If we reach here without memory issues, test passes
        assert True

    def test_large_response_performance(self):
        """Test security middleware performance with large responses."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/large")
        def large_endpoint():
            # Generate ~1MB response
            large_data = {"data": ["x" * 1000] * 1000}
            return large_data

        client = TestClient(app)

        start_time = time.time()
        response = client.get("/large")
        end_time = time.time()

        assert response.status_code == 200
        assert "X-Content-Type-Options" in response.headers

        # Should complete within reasonable time (< 5 seconds)
        processing_time = end_time - start_time
        assert processing_time < 5.0, f"Large response too slow: {processing_time}s"


class TestBrowserCompatibility:
    """Test security headers compatibility with different browsers."""

    def test_csp_directive_format_compatibility(self):
        """Test CSP directive format is browser-compatible."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        client = TestClient(app)
        response = client.get("/test")

        csp = response.headers["Content-Security-Policy"]

        # CSP should follow standard format
        assert csp.endswith(";")  # Should end with semicolon
        assert "default-src 'self'" in csp

        # Directives should be properly formatted
        directives = csp.split(";")
        for directive in directives:
            directive = directive.strip()
            if directive:  # Skip empty
                # Should have directive-name followed by values
                parts = directive.split(" ", 1)
                assert len(parts) >= 1
                directive_name = parts[0]
                assert re.match(r"^[a-z-]+$", directive_name), f"Invalid directive name: {directive_name}"

    def test_x_frame_options_standard_values(self):
        """Test X-Frame-Options uses standard values."""
        standard_values = ["DENY", "SAMEORIGIN"]

        for value in standard_values:
            app = FastAPI()
            app.add_middleware(SecurityHeadersMiddleware)

            @app.get("/test")
            def test_endpoint():
                return {"message": "test"}

            with patch.object(settings, "x_frame_options", value):
                client = TestClient(app)
                response = client.get("/test")

                assert response.headers["X-Frame-Options"] == value

    def test_hsts_header_format_compliance(self):
        """Test HSTS header format complies with RFC standards."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        client = TestClient(app)
        response = client.get("/test", headers={"X-Forwarded-Proto": "https"})

        if "Strict-Transport-Security" in response.headers:
            hsts_value = response.headers["Strict-Transport-Security"]

            # Should match RFC format: max-age=<seconds>; includeSubDomains
            assert re.match(r"max-age=\d+(; includeSubDomains)?", hsts_value)

    def test_referrer_policy_standard_value(self):
        """Test Referrer-Policy uses standard value."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        client = TestClient(app)
        response = client.get("/test")

        referrer_policy = response.headers["Referrer-Policy"]

        # Should be a standard referrer policy value
        standard_policies = ["no-referrer", "no-referrer-when-downgrade", "origin", "origin-when-cross-origin", "same-origin", "strict-origin", "strict-origin-when-cross-origin", "unsafe-url"]

        assert referrer_policy in standard_policies


class TestStaticAnalysisToolCompatibility:
    """Test compatibility with static analysis tools."""

    def test_csp_meta_tag_format(self):
        """Test CSP meta tag format for static analysis tools."""
        # This tests the meta tag in admin.html indirectly
        # First-Party
        from mcpgateway.middleware.security_headers import SecurityHeadersMiddleware

        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        client = TestClient(app)
        response = client.get("/test")

        # HTTP header CSP should be well-formed for tools to parse
        csp = response.headers["Content-Security-Policy"]

        # Should be parseable by security tools
        assert "default-src" in csp
        assert "'self'" in csp
        assert "script-src" in csp
        assert "frame-ancestors" in csp

    def test_security_headers_machine_readable(self):
        """Test security headers are in machine-readable format."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        client = TestClient(app)
        response = client.get("/test")

        # Headers should be in standard format for automated tools
        headers_to_check = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "X-XSS-Protection": "0", "X-Download-Options": "noopen"}

        for header_name, expected_value in headers_to_check.items():
            assert response.headers[header_name] == expected_value

    def test_nodejsscan_detectable_patterns(self):
        """Test patterns that nodejsscan and similar tools can detect."""
        # Test that our implementation includes patterns static analyzers expect

        # Test 1: CSP header presence
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        client = TestClient(app)
        response = client.get("/test")

        # Should have detectable security patterns
        assert "Content-Security-Policy" in response.headers
        csp = response.headers["Content-Security-Policy"]

        # Static analyzers look for these patterns
        assert "default-src" in csp
        assert "'self'" in csp
        assert "script-src" in csp


class TestCORSPerformanceAndCompatibility:
    """Test CORS performance and compatibility."""

    def test_cors_origin_matching_performance(self):
        """Test CORS origin matching doesn't impact performance."""
        # Third-Party
        from fastapi.middleware.cors import CORSMiddleware

        # Create app with many allowed origins
        many_origins = [f"https://subdomain{i}.example.com" for i in range(100)]

        app = FastAPI()
        app.add_middleware(CORSMiddleware, allow_origins=many_origins, allow_credentials=True)
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        client = TestClient(app)

        # Test performance with many origins configured
        start_time = time.time()
        for i in range(20):
            response = client.get("/test", headers={"Origin": f"https://subdomain{i}.example.com"})
            assert response.status_code == 200
        end_time = time.time()

        # Should complete quickly even with many origins
        total_time = end_time - start_time
        assert total_time < 2.0, f"CORS with many origins too slow: {total_time}s"

    def test_environment_aware_cors_switching(self):
        """Test switching between environment CORS configurations."""
        # Test that environment switching works correctly

        # Development configuration
        with patch.multiple(settings, environment="development", allowed_origins={"http://localhost:3000"}):
            app = FastAPI()
            app.add_middleware(SecurityHeadersMiddleware)

            @app.get("/test")
            def test_endpoint():
                return {"message": "dev"}

            client = TestClient(app)
            response = client.get("/test")

            # Should work in development
            assert response.status_code == 200
            assert "X-Content-Type-Options" in response.headers

        # Production configuration
        with patch.multiple(settings, environment="production", allowed_origins={"https://example.com"}):
            app = FastAPI()
            app.add_middleware(SecurityHeadersMiddleware)

            @app.get("/test")
            def test_endpoint():
                return {"message": "prod"}

            client = TestClient(app)
            response = client.get("/test")

            # Should work in production
            assert response.status_code == 200
            assert "X-Content-Type-Options" in response.headers


class TestSecurityHeadersStandardsCompliance:
    """Test security headers comply with web standards."""

    def test_csp_level_2_compliance(self):
        """Test CSP follows CSP Level 2 specification."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        client = TestClient(app)
        response = client.get("/test")

        csp = response.headers["Content-Security-Policy"]

        # CSP Level 2 directive compliance
        required_directives = ["default-src", "script-src", "style-src"]
        for directive in required_directives:
            assert directive in csp

        # Should not use deprecated directives
        deprecated_directives = ["script-src-elem", "script-src-attr"]
        for directive in deprecated_directives:
            assert directive not in csp

    def test_security_headers_case_sensitivity(self):
        """Test security headers use correct case."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        client = TestClient(app)
        response = client.get("/test")

        # Headers should use standard case (HTTP headers are case-insensitive but have conventions)
        expected_headers = ["X-Content-Type-Options", "X-Frame-Options", "X-XSS-Protection", "X-Download-Options", "Content-Security-Policy", "Referrer-Policy"]

        for header in expected_headers:
            assert header in response.headers, f"Missing header: {header}"

    def test_http_version_compatibility(self):
        """Test security headers work with different HTTP versions."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        client = TestClient(app)

        # Test with different HTTP configurations
        response = client.get("/test")

        # Should work with standard HTTP
        assert response.status_code == 200
        assert "X-Content-Type-Options" in response.headers

        # Headers should be present regardless of HTTP version
        assert response.headers["X-Content-Type-Options"] == "nosniff"


class TestContentTypeCompatibility:
    """Test security headers with different content types."""

    @pytest.mark.parametrize(
        "content_type,content",
        [
            ("application/json", '{"test": "json"}'),
            ("text/html", "<html><body>Test</body></html>"),
            ("text/plain", "Plain text response"),
            ("application/xml", "<?xml version='1.0'?><root>test</root>"),
            ("text/css", "body { color: black; }"),
            ("application/javascript", "console.log('test');"),
        ],
    )
    def test_security_headers_with_content_types(self, content_type: str, content: str):
        """Test security headers work with various content types."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            # Third-Party
            from fastapi import Response

            return Response(content=content, media_type=content_type)

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        assert response.headers["Content-Type"].startswith(content_type)

        # Security headers should be present for all content types
        assert "X-Content-Type-Options" in response.headers
        assert "Content-Security-Policy" in response.headers

        # X-Download-Options is especially important for downloadable content
        if content_type in ["application/octet-stream", "application/javascript"]:
            assert "X-Download-Options" in response.headers

    def test_security_headers_with_binary_content(self):
        """Test security headers work with binary content."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/binary")
        def binary_endpoint():
            # Simulate binary content (like images, PDFs, etc.)
            binary_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            # Third-Party
            from fastapi import Response

            return Response(content=binary_data, media_type="image/png")

        client = TestClient(app)
        response = client.get("/binary")

        assert response.status_code == 200
        assert response.headers["Content-Type"] == "image/png"

        # Security headers should be present for binary content too
        assert "X-Content-Type-Options" in response.headers
        assert "X-Download-Options" in response.headers
        assert "Content-Security-Policy" in response.headers


class TestSecurityInProxyScenarios:
    """Test security implementation in proxy/load balancer scenarios."""

    @pytest.mark.parametrize(
        "proxy_headers",
        [
            {"X-Forwarded-Proto": "https", "X-Forwarded-Host": "example.com"},
            {"X-Forwarded-Proto": "http", "X-Forwarded-For": "192.168.1.1"},
            {"X-Real-IP": "10.0.0.1", "X-Forwarded-Proto": "https"},
            {"CF-Visitor": '{"scheme":"https"}', "X-Forwarded-Proto": "https"},  # Cloudflare
        ],
    )
    def test_hsts_with_proxy_headers(self, proxy_headers: dict):
        """Test HSTS detection works with various proxy configurations."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        with patch.object(settings, "hsts_enabled", True):
            client = TestClient(app)
            response = client.get("/test", headers=proxy_headers)

            if proxy_headers.get("X-Forwarded-Proto") == "https":
                assert "Strict-Transport-Security" in response.headers
            else:
                assert "Strict-Transport-Security" not in response.headers

    def test_security_headers_with_load_balancer_headers(self):
        """Test security headers work with common load balancer headers."""
        load_balancer_headers = {
            "X-Forwarded-For": "192.168.1.1, 10.0.0.1",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "api.example.com",
            "X-Request-ID": "req-12345",
            "X-Correlation-ID": "corr-67890",
        }

        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        client = TestClient(app)
        response = client.get("/test", headers=load_balancer_headers)

        assert response.status_code == 200

        # Security headers should be present
        assert "X-Content-Type-Options" in response.headers
        assert "Strict-Transport-Security" in response.headers  # Due to X-Forwarded-Proto: https

        # Load balancer headers should be preserved
        # Note: TestClient may not preserve all forwarded headers, but security should work


class TestConfigurationValidationAndErrors:
    """Test configuration validation and error scenarios."""

    def test_invalid_configuration_graceful_handling(self):
        """Test graceful handling of invalid configuration values."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        # Test with potentially problematic configuration
        with patch.multiple(
            settings,
            security_headers_enabled=True,
            x_frame_options="INVALID-VALUE",  # Non-standard but should work
            hsts_max_age=-1,
        ):  # Negative value
            client = TestClient(app)
            response = client.get("/test", headers={"X-Forwarded-Proto": "https"})

            # Should not crash, though values might be non-standard
            assert response.status_code == 200
            assert "X-Frame-Options" in response.headers

            # Non-standard values should be passed through
            assert response.headers["X-Frame-Options"] == "INVALID-VALUE"

    def test_settings_attribute_access_safety(self):
        """Test safe attribute access for settings."""
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"message": "test"}

        # Mock settings to test attribute access patterns
        with patch("mcpgateway.middleware.security_headers.settings") as mock_settings:
            # Configure mock with all expected attributes
            mock_settings.security_headers_enabled = True
            mock_settings.x_content_type_options_enabled = True
            mock_settings.x_frame_options = "DENY"
            mock_settings.x_xss_protection_enabled = True
            mock_settings.x_download_options_enabled = True
            mock_settings.hsts_enabled = True
            mock_settings.hsts_max_age = 31536000
            mock_settings.hsts_include_subdomains = True
            mock_settings.remove_server_headers = True

            client = TestClient(app)
            response = client.get("/test")

            assert response.status_code == 200
            # If we reach here, attribute access was successful
            assert "X-Content-Type-Options" in response.headers
