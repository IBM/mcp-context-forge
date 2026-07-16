# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_openapi_spec.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0
Authors: Contributors to the MCP-CONTEXT-FORGE project

Integration tests for OpenAPI specification content.

Verifies that the OpenAPI spec correctly includes/excludes routes based on
API versioning strategy.
"""

import pytest


@pytest.mark.integration
def test_legacy_routes_not_in_openapi_spec(app_with_temp_db):
    """Verify legacy routes excluded from main OpenAPI spec.

    Legacy (unversioned) routes should not appear in the OpenAPI spec
    to avoid duplication. Only /v1/* routes should be documented.

    Exceptions: Permanently unversioned routes like /health, /oauth, etc.
    are allowed.
    """
    # Access OpenAPI spec directly from app object (bypasses HTTP auth)
    spec = app_with_temp_db.openapi()
    paths = spec.get("paths", {})

    # Find all unversioned paths (not starting with /v1)
    legacy_paths = [p for p in paths if not p.startswith("/v1")]

    # Allow permanently unversioned paths
    allowed_unversioned = [
        "/health",
        "/ready",
        "/oauth",
        "/.well-known",
        "/version",
        "/favicon.ico",
        "/",
    ]

    # Filter out allowed paths
    unexpected = [
        p for p in legacy_paths
        if not any(p.startswith(a) or p == a for a in allowed_unversioned)
    ]

    assert not unexpected, (
        f"Legacy routes found in OpenAPI spec (should be excluded): {unexpected}. "
        f"These routes should only appear under /v1 prefix."
    )


@pytest.mark.integration
def test_v1_routes_in_openapi_spec(app_with_temp_db):
    """Verify /v1/* routes are present in OpenAPI spec.

    The canonical /v1 routes should be the source of truth for API
    documentation.
    """
    spec = app_with_temp_db.openapi()
    paths = spec.get("paths", {})

    # Find all versioned paths
    v1_paths = [p for p in paths if p.startswith("/v1")]

    # Should have core routes (these are always mounted)
    expected_core_routes = [
        "/v1/tools",
        "/v1/servers",
        "/v1/resources",
        "/v1/prompts",
        "/v1/gateways",
    ]

    missing = [route for route in expected_core_routes if route not in v1_paths]

    assert not missing, (
        f"Expected /v1 routes missing from OpenAPI spec: {missing}. "
        f"Found v1 paths: {v1_paths[:10]}..."  # Show first 10 for debugging
    )


@pytest.mark.integration
def test_openapi_spec_has_version_info(app_with_temp_db):
    """Verify OpenAPI spec includes version information."""
    spec = app_with_temp_db.openapi()

    # Should have info section with version
    assert "info" in spec, "OpenAPI spec missing 'info' section"
    assert "version" in spec["info"], "OpenAPI spec missing version"
    assert "title" in spec["info"], "OpenAPI spec missing title"


@pytest.mark.integration
def test_openapi_spec_accessible_at_standard_path(app_with_temp_db):
    """Verify OpenAPI spec is accessible at standard path."""
    spec = app_with_temp_db.openapi()

    # Should be valid OpenAPI spec
    assert "openapi" in spec, "Not a valid OpenAPI spec"
    assert spec["openapi"].startswith("3."), "Should be OpenAPI 3.x"
