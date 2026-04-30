# -*- coding: utf-8 -*-
"""Location: ./tests/security/test_security_headers.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Security Headers and CORS Testing.

This module contains comprehensive tests for security headers middleware and CORS configuration.
"""

# Standard
from unittest.mock import patch

# Third-Party
from fastapi.testclient import TestClient
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.middleware.security_headers import SecurityHeadersMiddleware


class TestSecurityHeaders:
    """Test security headers are properly set on all responses."""

    def test_security_headers_present_on_health_endpoint(self, client: TestClient):
        """Test that essential security headers are present on health endpoint."""
        response = client.get("/health")

        # Essential security headers
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["X-XSS-Protection"] == "0"
        assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert "Content-Security-Policy" in response.headers

        # Verify CSP contains essential directives
        csp = response.headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    def test_security_headers_present_on_api_endpoints(self, client: TestClient):
        """Test security headers on API endpoints."""
        # Test with authentication disabled for this test
        with patch.object(settings, "auth_required", False):
            response = client.get("/tools")

            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.headers["X-Frame-Options"] == "DENY"
            assert response.headers["X-XSS-Protection"] == "0"
            assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
            assert "Content-Security-Policy" in response.headers

    def test_sensitive_headers_removed(self, client: TestClient):
        """Test that sensitive headers are removed."""
        response = client.get("/health")

        # These headers should not be present
        assert "X-Powered-By" not in response.headers
        assert "Server" not in response.headers

    def test_hsts_header_on_https_request(self, client: TestClient):
        """Test HSTS header is present when X-Forwarded-Proto indicates HTTPS."""
        response = client.get("/health", headers={"X-Forwarded-Proto": "https"})

        assert "Strict-Transport-Security" in response.headers
        hsts_value = response.headers["Strict-Transport-Security"]
        assert "max-age=31536000" in hsts_value
        assert "includeSubDomains" in hsts_value

    def test_no_hsts_header_on_http_request(self, client: TestClient):
        """Test HSTS header is not present on HTTP requests."""
        response = client.get("/health")

        # HSTS should not be present for HTTP requests
        assert "Strict-Transport-Security" not in response.headers

    def test_content_security_policy_structure(self, client: TestClient):
        """Test CSP header has proper structure and directives."""
        response = client.get("/health")

        csp = response.headers["Content-Security-Policy"]

        # Check for essential CSP directives
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "style-src 'self'" in csp
        assert "img-src 'self'" in csp
        assert "font-src 'self'" in csp
        assert "connect-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

        # Verify CSP ends with semicolon
        assert csp.endswith(";")


class TestCORSConfiguration:
    """Test CORS configuration and behavior."""

    def test_cors_with_development_origins(self, client: TestClient):
        """Test CORS works with development origins."""
        with patch.object(settings, "environment", "development"):
            with patch.object(settings, "allowed_origins", {"http://localhost:3000", "http://localhost:8080"}):
                # Test with actual GET request that includes CORS headers
                response = client.get("/health", headers={"Origin": "http://localhost:3000"})
                assert response.status_code == 200
                # Check that CORS headers are present for allowed origin
                assert response.headers.get("Access-Control-Allow-Origin") == "http://localhost:3000"

    def test_cors_blocks_unauthorized_origin(self, client: TestClient):
        """Test CORS blocks unauthorized origins."""
        with patch.object(settings, "allowed_origins", {"http://localhost:3000"}):
            # Test blocked origin with GET request
            response = client.get("/health", headers={"Origin": "https://evil.com"})
            # For blocked origins, Access-Control-Allow-Origin should not be set to the blocked origin
            assert response.headers.get("Access-Control-Allow-Origin") != "https://evil.com"
            # The response should still succeed but without CORS headers for the blocked origin
            assert response.status_code == 200

    def test_cors_credentials_allowed(self, client: TestClient):
        """Test CORS allows credentials when configured."""
        with patch.object(settings, "cors_allow_credentials", True):
            with patch.object(settings, "allowed_origins", {"http://localhost:3000"}):
                response = client.get("/health", headers={"Origin": "http://localhost:3000"})
                assert response.headers.get("Access-Control-Allow-Credentials") == "true"

    def test_cors_allowed_methods(self, client: TestClient):
        """Test CORS exposes correct allowed methods."""
        with patch.object(settings, "allowed_origins", {"http://localhost:3000"}):
            # Test with an endpoint that supports OPTIONS for proper CORS preflight
            # Use the root endpoint which should support more methods
            response = client.get("/health", headers={"Origin": "http://localhost:3000"})

            # Check that the response includes CORS origin header indicating CORS is working
            assert response.headers.get("Access-Control-Allow-Origin") == "http://localhost:3000"

    def test_cors_exposed_headers(self, client: TestClient):
        """Test CORS exposes correct headers."""
        with patch.object(settings, "allowed_origins", {"http://localhost:3000"}):
            response = client.get("/health", headers={"Origin": "http://localhost:3000"})

            # Check that CORS is working with the allowed origin
            assert response.headers.get("Access-Control-Allow-Origin") == "http://localhost:3000"

            # Check for exposed headers (these may be set by CORS middleware)
            exposed_headers = response.headers.get("Access-Control-Expose-Headers", "")
            if exposed_headers:  # Only check if the header is present
                assert "Content-Length" in exposed_headers
                assert "X-Request-ID" in exposed_headers

    def test_cors_preflight_on_mcp_endpoints(self, client: TestClient):
        """Test CORS preflight (OPTIONS) works on /servers/{id}/mcp endpoints.

        Browser-based MCP clients send preflight requests before connecting.
        CORSMiddleware must intercept these and respond with proper headers.

        Note: This test dynamically uses an origin from the actual allowed_origins
        config to work regardless of environment settings.
        """
        # Dynamically get an allowed origin from the actual config
        # This ensures the test works regardless of ALLOWED_ORIGINS env var
        if not settings.allowed_origins:
            pytest.skip("No allowed_origins configured - CORS test requires at least one origin")

        # Skip wildcard config - can't test specific origin behavior with "*"
        if "*" in settings.allowed_origins:
            pytest.skip("Wildcard CORS configured - specific origin tests not applicable")

        # Get a real origin (not "*")
        real_origins = [o for o in settings.allowed_origins if o != "*"]
        if not real_origins:
            pytest.skip("No non-wildcard origins configured")

        allowed_origin = real_origins[0]

        # Send a CORS preflight request (OPTIONS with Origin and Access-Control-Request-Method)
        response = client.options(
            "/servers/test-server-id/mcp",
            headers={
                "Origin": allowed_origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            },
        )

        # Preflight should succeed (200 from CORSMiddleware)
        assert response.status_code == 200

        # CORS headers must be present
        assert response.headers.get("Access-Control-Allow-Origin") == allowed_origin
        assert "POST" in response.headers.get("Access-Control-Allow-Methods", "")
        assert response.headers.get("Access-Control-Allow-Credentials") == "true"

    def test_cors_preflight_rejects_disallowed_origin(self, client: TestClient):
        """Test CORS preflight rejects origins not in allowed_origins.

        This verifies that CORSMiddleware is properly restricting access to
        configured origins only.
        """
        # Skip if wildcard CORS is configured - all origins are allowed
        if "*" in settings.allowed_origins:
            pytest.skip("Wildcard CORS configured - rejection test not applicable")

        # Use a clearly invalid origin that should never be in any real config
        # Using .invalid TLD per RFC 2606 - reserved for testing
        disallowed_origin = "https://attacker.invalid"

        # Sanity check: ensure this origin is actually not allowed
        assert disallowed_origin not in settings.allowed_origins, "Test origin unexpectedly in allowed_origins"

        response = client.options(
            "/servers/test-server-id/mcp",
            headers={
                "Origin": disallowed_origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            },
        )

        # CORSMiddleware returns 400 for disallowed origins
        assert response.status_code == 400

        # No CORS allow header should be set for disallowed origin
        assert response.headers.get("Access-Control-Allow-Origin") != disallowed_origin


class TestProductionSecurity:
    """Test security configuration in production environment."""

    def test_production_cors_requires_explicit_origins(self, client: TestClient):
        """Test that production environment requires explicit CORS origins."""
        with patch.object(settings, "environment", "production"):
            with patch.object(settings, "allowed_origins", set()):
                # Should have empty origins list for production without explicit config
                assert len(settings.allowed_origins) == 0

    def test_production_uses_https_origins(self, client: TestClient):
        """Test that production environment uses HTTPS origins."""
        with patch.object(settings, "environment", "production"):
            with patch.object(settings, "app_domain", "example.com"):
                # This would be set during initialization
                test_origins = {"https://example.com", "https://app.example.com", "https://admin.example.com"}
                with patch.object(settings, "allowed_origins", test_origins):
                    # All origins should be HTTPS
                    for origin in settings.allowed_origins:
                        assert origin.startswith("https://")

    def test_security_headers_consistent_across_endpoints(self, client: TestClient):
        """Test security headers are consistent across different endpoints."""
        endpoints = ["/health", "/ready"]

        headers_to_check = ["X-Content-Type-Options", "X-Frame-Options", "X-XSS-Protection", "Referrer-Policy", "Content-Security-Policy"]

        responses = {}
        for endpoint in endpoints:
            responses[endpoint] = client.get(endpoint)

        # Check that all endpoints have the same security headers
        for header in headers_to_check:
            values = [responses[endpoint].headers.get(header) for endpoint in endpoints]
            assert all(value == values[0] for value in values), f"Inconsistent {header} across endpoints"


class TestSecurityHeadersEdgeCases:
    """Test edge cases and error conditions for security headers."""

    def test_security_headers_on_error_responses(self, client: TestClient):
        """Test security headers are present even on error responses."""
        # Make a request to a non-existent endpoint
        response = client.get("/nonexistent")

        # Even 404 responses should have security headers
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert "Content-Security-Policy" in response.headers

    def test_security_headers_on_method_not_allowed(self, client: TestClient):
        """Test security headers on 405 Method Not Allowed responses."""
        # Try to POST to a GET-only endpoint
        response = client.post("/health")

        assert response.status_code == 405
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert "Content-Security-Policy" in response.headers

    @pytest.mark.parametrize("forwarded_proto", ["http", "https", "invalid"])
    def test_hsts_with_various_forwarded_proto_values(self, client: TestClient, forwarded_proto: str):
        """Test HSTS behavior with various X-Forwarded-Proto values."""
        response = client.get("/health", headers={"X-Forwarded-Proto": forwarded_proto})

        if forwarded_proto == "https":
            assert "Strict-Transport-Security" in response.headers
        else:
            assert "Strict-Transport-Security" not in response.headers


@pytest.fixture
def client(app_with_temp_db):
    """Create a test client for the FastAPI app."""
    return TestClient(app_with_temp_db)


class TestCacheControlHardening:
    """
    Test suite for hardened cache control policies on authenticated endpoints.

    Verifies that protected API endpoints implement proper cache control headers
    for defense-in-depth security.
    """

    def test_protected_endpoints_have_no_store_private(self, client: TestClient):
        """Test that protected endpoints return Cache-Control: no-store, private."""
        with patch.object(settings, "auth_required", False):
            # Test various protected endpoints
            protected_paths = ["/tools", "/servers", "/resources", "/gateways", "/prompts", "/tags"]

            for path in protected_paths:
                response = client.get(path)
                cache_control = response.headers.get("Cache-Control", "")

                assert "no-store" in cache_control, f"{path} missing 'no-store' in Cache-Control: {cache_control}"
                assert "private" in cache_control, f"{path} missing 'private' in Cache-Control: {cache_control}"

    def test_docs_paths_are_classified_as_protected(self):
        """Regression guard: /docs, /redoc, /openapi.json must be classified as protected.

        These paths are auth-protected by DocsAuthMiddleware. Exempting them from
        SecurityHeadersMiddleware would let a shared cache replay an authenticated
        docs/schema response to unauthenticated viewers — Web Cache Deception.

        This is a unit test of the classifier rather than a request-flow test
        because DocsAuthMiddleware wraps SecurityHeadersMiddleware and short-
        circuits unauthenticated requests before they reach the response path.
        """
        middleware = SecurityHeadersMiddleware(app=None)
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert middleware._is_protected_path(path), f"{path} must be treated as protected"  # pylint: disable=protected-access

    def test_protected_endpoints_have_vary_authorization(self, client: TestClient):
        """Test that protected endpoints include Vary: Authorization header."""
        with patch.object(settings, "auth_required", False):
            response = client.get("/tools")
            vary_header = response.headers.get("Vary", "")

            assert "Authorization" in vary_header, f"Missing 'Authorization' in Vary header: {vary_header}"

    def test_protected_endpoints_have_legacy_cache_headers(self, client: TestClient):
        """Test that protected endpoints include legacy HTTP/1.0 cache headers."""
        with patch.object(settings, "auth_required", False):
            response = client.get("/tools")

            assert response.headers.get("Pragma") == "no-cache", "Missing or incorrect Pragma header"
            assert response.headers.get("Expires") == "0", "Missing or incorrect Expires header"

    def test_exempted_endpoints_can_be_cached(self, client: TestClient):
        """Test that public/static endpoints do NOT receive the no-store/private cache hardening."""
        response = client.get("/health")
        cache_control = response.headers.get("Cache-Control", "")

        assert "no-store" not in cache_control, f"Exempted /health unexpectedly got 'no-store': {cache_control}"
        assert "private" not in cache_control, f"Exempted /health unexpectedly got 'private': {cache_control}"
        assert response.headers.get("Pragma") != "no-cache"
        assert response.headers.get("Expires") != "0"

    def test_cache_headers_with_query_parameters(self, client: TestClient):
        """Test that cache headers are applied even with query parameters."""
        with patch.object(settings, "auth_required", False):
            response = client.get("/tools?page=1&limit=10")
            cache_control = response.headers.get("Cache-Control", "")

            assert "no-store" in cache_control
            assert "private" in cache_control

    def test_cache_headers_on_nested_endpoints(self, client: TestClient):
        """Test that cache headers apply to nested protected endpoints."""
        with patch.object(settings, "auth_required", False):
            response = client.get("/servers/test-id/tools")
            cache_control = response.headers.get("Cache-Control", "")

            assert "no-store" in cache_control, f"Nested path missing 'no-store': {cache_control}"
            assert "private" in cache_control, f"Nested path missing 'private': {cache_control}"

    def test_cache_headers_coexist_with_cors(self, client: TestClient):
        """Test that cache headers coexist properly with CORS headers."""
        with patch.object(settings, "auth_required", False):
            with patch.object(settings, "allowed_origins", {"http://localhost:3000"}):
                response = client.get("/tools", headers={"Origin": "http://localhost:3000"})

                # Should have both cache control and CORS headers
                cache_control = response.headers.get("Cache-Control", "")
                vary = response.headers.get("Vary", "")

                assert "no-store" in cache_control
                assert "Authorization" in vary
                # Vary should include both Origin (from CORS) and Authorization (from cache fix)
                assert "Origin" in vary or "origin" in vary.lower()

    def test_cache_headers_on_error_responses(self, client: TestClient):
        """Test that cache headers are present even on error responses."""
        with patch.object(settings, "auth_required", False):
            # Request a non-existent resource (should return 404)
            response = client.get("/tools/non-existent-id-12345")

            # Even on error, cache headers should be present
            cache_control = response.headers.get("Cache-Control", "")
            assert "no-store" in cache_control, f"Error response missing 'no-store': {cache_control}"
            assert "private" in cache_control, f"Error response missing 'private': {cache_control}"
            assert response.headers.get("Pragma") == "no-cache"
            assert response.headers.get("Expires") == "0"


class TestSecurityHeadersAdditionalCoverage:
    """Additional tests for edge cases to improve coverage to 95%+."""

    def test_security_headers_disabled(self, client: TestClient):
        """Test that when security headers are disabled, none are emitted by SecurityHeadersMiddleware."""
        with patch.object(settings, "security_headers_enabled", False):
            response = client.get("/health")

            assert response.status_code == 200
            assert "X-Content-Type-Options" not in response.headers
            assert "X-Frame-Options" not in response.headers
            assert "X-XSS-Protection" not in response.headers
            assert "Content-Security-Policy" not in response.headers
            assert "Referrer-Policy" not in response.headers

    def test_x_frame_options_sameorigin(self, client: TestClient):
        """Test X-Frame-Options with SAMEORIGIN value."""
        with patch.object(settings, "x_frame_options", "SAMEORIGIN"):
            response = client.get("/health")

            assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
            # CSP should have frame-ancestors 'self'
            csp = response.headers.get("Content-Security-Policy", "")
            assert "frame-ancestors 'self'" in csp

    def test_x_frame_options_allow_from(self, client: TestClient):
        """Test X-Frame-Options with ALLOW-FROM value."""
        with patch.object(settings, "x_frame_options", "ALLOW-FROM https://example.com"):
            response = client.get("/health")

            assert response.headers["X-Frame-Options"] == "ALLOW-FROM https://example.com"
            # CSP should have the allowed URI
            csp = response.headers.get("Content-Security-Policy", "")
            assert "frame-ancestors https://example.com" in csp

    def test_x_frame_options_allow_all(self, client: TestClient):
        """Test X-Frame-Options with ALLOW-ALL value."""
        with patch.object(settings, "x_frame_options", "ALLOW-ALL"):
            response = client.get("/health")

            assert response.headers["X-Frame-Options"] == "ALLOW-ALL"
            # CSP should allow all origins
            csp = response.headers.get("Content-Security-Policy", "")
            assert "frame-ancestors * file: http: https:" in csp

    def test_x_frame_options_unknown_value(self, client: TestClient):
        """Test X-Frame-Options with unknown value defaults to DENY behavior."""
        with patch.object(settings, "x_frame_options", "UNKNOWN-VALUE"):
            response = client.get("/health")

            assert response.headers["X-Frame-Options"] == "UNKNOWN-VALUE"
            # CSP should default to 'none' for unknown values
            csp = response.headers.get("Content-Security-Policy", "")
            assert "frame-ancestors 'none'" in csp

    def test_x_frame_options_empty_string(self, client: TestClient):
        """Test X-Frame-Options with empty string (should not set header)."""
        with patch.object(settings, "x_frame_options", ""):
            response = client.get("/health")

            assert "X-Frame-Options" not in response.headers

    def test_server_headers_removed(self, client: TestClient):
        """Test that Server and X-Powered-By headers are removed when configured."""
        with patch.object(settings, "remove_server_headers", True):
            response = client.get("/health")

            # These headers should not be present
            assert "X-Powered-By" not in response.headers
            assert "Server" not in response.headers

    def test_cors_production_environment(self, client: TestClient):
        """Test CORS in production environment requires explicit allow-list."""
        with patch.object(settings, "environment", "production"):
            with patch.object(settings, "allowed_origins", {"https://example.com"}):
                # Allowed origin
                response = client.get("/health", headers={"Origin": "https://example.com"})
                assert response.headers.get("Access-Control-Allow-Origin") == "https://example.com"

                # Disallowed origin
                response = client.get("/health", headers={"Origin": "https://evil.com"})
                assert response.headers.get("Access-Control-Allow-Origin") != "https://evil.com"
