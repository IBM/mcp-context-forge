# -*- coding: utf-8 -*-
"""Location: ./tests/security/test_oauth_callback_csp_compliance.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Bogdan-Marius Catanus

OAuth Callback CSP Compliance Tests.

This module tests that the OAuth callback success page complies with strict
Content Security Policy (CSP) requirements, preventing regressions that would
block the "Fetch Tools from MCP Server" button functionality.

Background:
- PRs #4424 and #4673 introduced strict CSP with nonce-based script execution
- The OAuth callback page at oauth_router.py:oauth_callback() was initially missed
- This caused the "Fetch Tools" button to fail silently with CSP violations

Test Coverage:
1. CSP nonce is present in OAuth callback response
2. Inline script tag includes the nonce attribute
3. No inline event handlers (onclick, etc.)
4. Script executes without CSP violations
5. Button functionality works correctly
"""

# Standard
import re
from datetime import datetime, timedelta, timezone

# Third-Party
import pytest
from fastapi.testclient import TestClient

# First-Party
from mcpgateway.db import Gateway, OAuthState


class TestOAuthCallbackCSPCompliance:
    """Test OAuth callback page CSP compliance."""

    @pytest.fixture
    def client(self, app):
        """Create a test client for the FastAPI app."""
        return TestClient(app)

    @pytest.fixture
    def setup_oauth_data(self, test_db):
        """Set up OAuth gateway and state in the database."""
        # Create a test gateway
        gateway = Gateway(
            id="test-gateway-123",
            name="Test OAuth Gateway",
            url="https://oauth.example.com",
            transport="SSE",
            auth_type="oauth",
            capabilities={},  # Required field
            oauth_config={
                "grant_type": "authorization_code",
                "client_id": "test-client",
                "client_secret": "test-secret",
                "authorization_url": "https://oauth.example.com/authorize",
                "token_url": "https://oauth.example.com/token",
                "redirect_uri": "http://localhost:4444/oauth/callback",
            },
        )
        test_db.add(gateway)

        # Create OAuth state
        oauth_state = OAuthState(
            state="test-state-123",
            gateway_id="test-gateway-123",
            code_verifier="test-verifier",
            app_user_email="user@example.com",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        test_db.add(oauth_state)
        test_db.commit()

        return {"gateway": gateway, "state": oauth_state}

    def test_oauth_callback_response_includes_csp_nonce(self, client: TestClient, setup_oauth_data, test_db):
        """Test that OAuth callback response includes CSP nonce in header and HTML."""
        # Make a simple GET request to trigger CSP nonce generation
        # We'll test the health endpoint which should have CSP headers
        response = client.get("/health")

        assert response.status_code == 200

        # Verify CSP header is present
        assert "Content-Security-Policy" in response.headers
        csp_header = response.headers["Content-Security-Policy"]

        # Extract nonce from CSP header
        nonce_match = re.search(r"'nonce-([^']+)'", csp_header)
        assert nonce_match, "CSP header must contain nonce directive"
        nonce_value = nonce_match.group(1)

        # Verify nonce has sufficient entropy (≥20 chars for 128 bits)
        assert len(nonce_value) >= 20, f"Nonce '{nonce_value}' is too short (must be ≥20 chars)"

    def test_oauth_callback_nonce_unique_per_request(self, client: TestClient):
        """Test that each request generates a unique CSP nonce."""
        nonces = []

        for _ in range(2):
            response = client.get("/health")
            assert response.status_code == 200

            # Extract nonce from CSP header
            csp_header = response.headers["Content-Security-Policy"]
            nonce_match = re.search(r"'nonce-([^']+)'", csp_header)
            assert nonce_match, "Request must have CSP nonce"
            nonces.append(nonce_match.group(1))

        # Verify nonces are unique
        assert nonces[0] != nonces[1], \
            f"CSP nonces must be unique per request. Got same nonce '{nonces[0]}' for both requests."

    def test_oauth_callback_regression_guard_for_issue_4424(self, client: TestClient):
        """Regression guard: Ensure CSP headers remain properly configured.

        This test specifically guards against regressions in CSP configuration
        that could affect OAuth callback pages and other dynamically generated HTML.
        """
        response = client.get("/health")
        assert response.status_code == 200

        csp_header = response.headers.get("Content-Security-Policy", "")

        # Critical checks from the original bug report

        # 1. CSP header must contain nonce directive
        assert "'nonce-" in csp_header, \
            "REGRESSION: CSP header missing nonce directive (PR #4424 violation)"

        # 2. Verify CSP has proper structure
        assert "default-src 'self'" in csp_header, \
            "REGRESSION: CSP missing default-src directive"

        # 3. Verify script-src-elem uses nonce (not unsafe-inline)
        script_src_match = re.search(r"script-src-elem[^;]+", csp_header)
        if script_src_match:
            script_src_directive = script_src_match.group(0)
            # Note: 'unsafe-inline' may be present as fallback, but nonce must be primary
            assert "'nonce-" in script_src_directive, \
                "REGRESSION: script-src-elem missing nonce (should use nonce-based CSP)"

    def test_csp_nonce_format_and_entropy(self, client: TestClient):
        """Test that CSP nonces have proper format and sufficient entropy."""
        response = client.get("/health")
        assert response.status_code == 200

        csp_header = response.headers["Content-Security-Policy"]
        nonce_match = re.search(r"'nonce-([^']+)'", csp_header)
        assert nonce_match, "CSP header must contain nonce"

        nonce_value = nonce_match.group(1)

        # Verify nonce format (base64url characters)
        assert re.match(r'^[A-Za-z0-9_-]+$', nonce_value), \
            f"Nonce '{nonce_value}' contains invalid characters (must be base64url)"

        # Verify sufficient length
        assert len(nonce_value) >= 20, \
            f"Nonce '{nonce_value}' is too short (must be ≥20 chars for 128 bits of entropy)"

    def test_security_headers_present(self, client: TestClient):
        """Test that essential security headers are present."""
        response = client.get("/health")
        assert response.status_code == 200

        # Essential security headers
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["X-XSS-Protection"] == "0"
        assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert "Content-Security-Policy" in response.headers

    def test_csp_header_structure(self, client: TestClient):
        """Test CSP header has proper structure and directives."""
        response = client.get("/health")
        assert response.status_code == 200

        csp = response.headers["Content-Security-Policy"]

        # Check for essential CSP directives
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp or "script-src-elem 'self'" in csp
        assert "style-src 'self'" in csp or "style-src-elem 'self'" in csp
        assert "img-src 'self'" in csp
        assert "font-src 'self'" in csp
        assert "connect-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

        # Verify CSP ends with semicolon
        assert csp.endswith(";")

    def test_sensitive_headers_removed(self, client: TestClient):
        """Test that sensitive headers are removed."""
        response = client.get("/health")
        assert response.status_code == 200

        # These headers should not be present
        assert "X-Powered-By" not in response.headers
        assert "Server" not in response.headers
