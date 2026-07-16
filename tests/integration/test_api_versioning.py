# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_api_versioning.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
Authors: Contributors to the MCP-CONTEXT-FORGE project

Integration tests for API versioning dual-mount architecture.

Tests verify:
- /v1/* routes work without deprecation headers
- Legacy routes work WITH deprecation headers
- Excluded routes remain unversioned
- LEGACY_API_ENABLED flag disables legacy routes
- Content parity between v1 and legacy routes
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from mcpgateway.config import settings
from mcpgateway.main import app


@pytest.fixture
def client():
    """Test client fixture."""
    return TestClient(app)


class TestV1RoutesWithoutDeprecation:
    """Verify /v1/* routes return 200 without deprecation headers."""

    @pytest.mark.parametrize(
        "path",
        [
            "/v1/tools",
            "/v1/servers",
            "/v1/gateways",
            "/v1/roots",
            "/v1/resources",
            "/v1/prompts",
            "/v1/protocol",
            "/v1/metrics",
            "/v1/tags",
        ],
    )
    def test_v1_routes_no_deprecation_headers(self, client: TestClient, path: str):
        """V1 routes should not include deprecation headers."""
        response = client.get(path)
        # May be 200, 401, or 403 depending on auth - we just care about headers
        assert "sunset" not in response.headers
        assert "deprecation" not in response.headers
        assert "x-deprecated-endpoint" not in response.headers

    def test_v1_admin_no_deprecation(self, client: TestClient):
        """V1 admin route should not include deprecation headers."""
        response = client.get("/v1/admin/")
        assert "sunset" not in response.headers
        assert "deprecation" not in response.headers


class TestLegacyRoutesWithDeprecation:
    """Verify legacy routes return WITH deprecation headers."""

    @pytest.mark.parametrize(
        "path,expected_successor",
        [
            ("/tools", "/v1/tools"),
            ("/servers", "/v1/servers"),
            ("/gateways", "/v1/gateways"),
            ("/roots", "/v1/roots"),
            ("/resources", "/v1/resources"),
            ("/prompts", "/v1/prompts"),
            ("/protocol", "/v1/protocol"),
            ("/metrics", "/v1/metrics"),
            ("/tags", "/v1/tags"),
        ],
    )
    def test_legacy_routes_have_deprecation_headers(self, client: TestClient, path: str, expected_successor: str):
        """Legacy routes should include all deprecation headers."""
        response = client.get(path)

        # Verify deprecation headers present
        assert "sunset" in response.headers
        assert response.headers["sunset"] == settings.legacy_api_sunset_date

        assert "deprecation" in response.headers
        assert response.headers["deprecation"] == "true"

        assert "link" in response.headers
        assert f"<{expected_successor}>; rel=\"successor-version\"" in response.headers["link"]

        assert "x-deprecated-endpoint" in response.headers
        assert expected_successor in response.headers["x-deprecated-endpoint"]
        assert settings.legacy_api_sunset_date in response.headers["x-deprecated-endpoint"]

    def test_legacy_admin_has_deprecation(self, client: TestClient):
        """Legacy admin route should include deprecation headers."""
        response = client.get("/admin/")
        assert "sunset" in response.headers
        assert "deprecation" in response.headers
        assert "</v1/admin/>; rel=\"successor-version\"" in response.headers.get("link", "")


class TestExcludedRoutesNoDeprecation:
    """Verify excluded routes remain unversioned without deprecation headers."""

    @pytest.mark.parametrize(
        "path",
        [
            "/health",
            "/ready",
            "/health/security",
            "/mcp",
            "/_internal/mcp/transport",
            "/version",
            "/favicon.ico",
            "/.well-known/security.txt",
        ],
    )
    def test_excluded_routes_no_deprecation(self, client: TestClient, path: str):
        """Excluded routes should not have deprecation headers."""
        response = client.get(path)
        # May be 200, 404, or other status - we just care about headers
        assert "sunset" not in response.headers
        assert "deprecation" not in response.headers
        assert "x-deprecated-endpoint" not in response.headers

    def test_oauth_routes_no_deprecation(self, client: TestClient):
        """OAuth routes should remain unversioned."""
        # OAuth routes may require specific setup, just verify no deprecation
        response = client.get("/oauth/authorize")
        assert "sunset" not in response.headers
        assert "deprecation" not in response.headers

    def test_servers_well_known_no_deprecation(self, client: TestClient):
        """Server-specific well-known URIs should not have deprecation."""
        response = client.get("/servers/test-server/.well-known/agent.json")
        assert "sunset" not in response.headers
        assert "deprecation" not in response.headers


class TestLegacyAPIEnabledFlag:
    """Verify LEGACY_API_ENABLED flag controls legacy route availability."""

    def test_legacy_routes_disabled_returns_404(self, client: TestClient):
        """When LEGACY_API_ENABLED=false, legacy routes should return 404.

        Note: This test requires app restart with LEGACY_API_ENABLED=false.
        The flag is checked at startup when mounting routes, not at runtime.
        Use deployment validation script (scripts/validate_legacy_disabled.py) instead.
        """
        pytest.skip(
            "Requires app restart with LEGACY_API_ENABLED=false. "
            "This is a deployment configuration test, not a runtime test. "
            "Use scripts/validate_legacy_disabled.py for deployment validation."
        )

    def test_v1_routes_always_available(self, client: TestClient):
        """V1 routes should work regardless of LEGACY_API_ENABLED setting."""
        with patch.object(settings, "legacy_api_enabled", False):
            response = client.get("/v1/tools")
            # Should work (may be 401/403 due to auth, but route exists)
            assert response.status_code != 404


class TestContentParity:
    """Verify v1 and legacy routes return identical content."""

    @pytest.mark.parametrize(
        "legacy_path,v1_path",
        [
            ("/tools", "/v1/tools"),
            ("/servers", "/v1/servers"),
            ("/gateways", "/v1/gateways"),
        ],
    )
    def test_v1_and_legacy_return_same_content(self, client: TestClient, legacy_path: str, v1_path: str):
        """V1 and legacy routes should return identical response bodies."""
        legacy_response = client.get(legacy_path)
        v1_response = client.get(v1_path)

        # Status codes should match
        assert legacy_response.status_code == v1_response.status_code

        # Response bodies should match
        assert legacy_response.content == v1_response.content

        # Content-Type should match
        assert legacy_response.headers.get("content-type") == v1_response.headers.get("content-type")

    def test_error_responses_match(self, client: TestClient):
        """Error responses should be identical between v1 and legacy."""
        # Test with a route that requires auth
        legacy_response = client.get("/tools/nonexistent-tool-id")
        v1_response = client.get("/v1/tools/nonexistent-tool-id")

        # Both should return same error status
        assert legacy_response.status_code == v1_response.status_code

        # Error message structure should match (excluding deprecation headers)
        if legacy_response.status_code >= 400:
            legacy_json = legacy_response.json()
            v1_json = v1_response.json()
            # Compare error structure (may vary by implementation)
            assert type(legacy_json) == type(v1_json)


class TestDeprecationHeaderFormat:
    """Verify deprecation headers follow RFC standards."""

    def test_sunset_header_rfc8594_format(self, client: TestClient):
        """Sunset header should follow RFC 8594 format."""
        response = client.get("/tools")
        sunset = response.headers.get("sunset")
        assert sunset is not None
        # Should be HTTP-date format: "Wed, 13 May 2026 00:00:00 GMT"
        assert "GMT" in sunset
        assert "2026" in sunset

    def test_deprecation_header_boolean(self, client: TestClient):
        """Deprecation header should be 'true' string."""
        response = client.get("/tools")
        assert response.headers.get("deprecation") == "true"

    def test_link_header_format(self, client: TestClient):
        """Link header should follow RFC 8288 format."""
        response = client.get("/tools")
        link = response.headers.get("link")
        assert link is not None
        assert link.startswith("<")
        assert ">; rel=\"successor-version\"" in link
        assert "/v1/" in link


class TestRootRedirect:
    """Verify root path redirects to versioned admin."""

    def test_root_redirects_to_v1_admin(self, client: TestClient):
        """Root path should redirect to /v1/admin/ when UI enabled."""
        response = client.get("/", follow_redirects=False)
        if response.status_code == 303:
            # UI enabled: should redirect to /v1/admin/
            assert response.headers["location"] == f"{settings.app_root_path}/v1/admin/"
        else:
            # UI disabled: returns API info
            assert response.status_code == 200


class TestOpenAPISchema:
    """Verify OpenAPI schema reflects v1 routes only."""

    def test_openapi_includes_v1_routes(self, client: TestClient):
        """OpenAPI schema should include /v1/* routes."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()

        # Check that v1 routes are present
        paths = schema.get("paths", {})
        assert any(path.startswith("/v1/") for path in paths.keys())

    def test_openapi_excludes_legacy_routes(self, client: TestClient):
        """OpenAPI schema should not include unversioned legacy routes."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()

        paths = schema.get("paths", {})
        # Legacy routes like /tools (without /v1) should not be in schema
        # (They may appear as /v1/tools)
        legacy_paths = ["/tools", "/servers", "/gateways"]
        for legacy_path in legacy_paths:
            # Exact legacy path should not exist
            assert legacy_path not in paths



class TestAdminStaticAssets:
    """Verify admin static assets are accessible without authentication."""

    def test_v1_admin_static_accessible_without_auth(self, client: TestClient):
        """Verify /v1/admin/static/* is accessible without authentication.

        This test ensures the AdminAuthMiddleware fix (Finding #1) works correctly.
        Static assets must be accessible for the login page to render properly.
        """
        # Test CSS file access (common static asset)
        response = client.get("/v1/admin/static/css/app.css")
        # Should be OK (200) or Not Modified (304), not 401/403
        assert response.status_code in [200, 304, 404], (
            f"Static asset returned {response.status_code}. "
            f"Expected 200/304 (if exists) or 404 (if missing), not auth error."
        )

        # If we got 401 or 403, the exemption is not working
        assert response.status_code not in [401, 403], (
            "Static assets should not require authentication. "
            "Check AdminAuthMiddleware.EXEMPT_PATHS includes /v1/admin/static"
        )

    def test_legacy_admin_static_accessible_without_auth(self, client: TestClient):
        """Verify /admin/static/* (legacy path) is also accessible."""
        response = client.get("/admin/static/css/app.css")
        assert response.status_code in [200, 304, 404]
        assert response.status_code not in [401, 403]


class TestAdminAuthMiddlewareProtection:
    """Verify AdminAuthMiddleware blocks unauthenticated/non-admin access to non-static admin routes."""

    def test_unauthenticated_v1_admin_route_rejected(self, client: TestClient):
        """Unauthenticated request to /v1/admin/ must return 401 or 403 (not 200)."""
        with patch.object(settings, "auth_required", True):
            response = client.get("/v1/admin/", follow_redirects=False)
        assert response.status_code in [401, 403, 302], (
            f"/v1/admin/ returned {response.status_code} without auth — expected 401/403/302 redirect to login"
        )
        assert response.status_code != 200, "Unauthenticated access to /v1/admin/ must not return 200"

    def test_unauthenticated_legacy_admin_route_rejected(self, client: TestClient):
        """Unauthenticated request to legacy /admin/ must also be rejected."""
        with patch.object(settings, "auth_required", True):
            response = client.get("/admin/", follow_redirects=False)
        assert response.status_code in [401, 403, 302]
        assert response.status_code != 200

    def test_v1_admin_login_exempt_from_auth(self, client: TestClient):
        """Login page /v1/admin/login must be reachable without credentials."""
        response = client.get("/v1/admin/login", follow_redirects=False)
        assert response.status_code not in [401, 403], (
            "/v1/admin/login is in EXEMPT_PATHS and must not require authentication"
        )

    def test_v1_admin_logout_exempt_from_auth(self, client: TestClient):
        """Logout /v1/admin/logout must be reachable without credentials."""
        response = client.get("/v1/admin/logout", follow_redirects=False)
        assert response.status_code not in [401, 403]
