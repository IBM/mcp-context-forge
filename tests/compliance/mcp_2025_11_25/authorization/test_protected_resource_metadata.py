# -*- coding: utf-8 -*-
"""Authorization discovery checks for protected resource metadata endpoints."""

# Third-Party
import pytest


@pytest.mark.mcp20251125
@pytest.mark.mcp_auth
@pytest.mark.mcp_optional
def test_deprecated_query_param_well_known_endpoint_is_not_supported(
    compliance_client,
    ensure_not_auth_error,
):
    response = compliance_client.get("/.well-known/oauth-protected-resource")
    ensure_not_auth_error(response)
    assert response.status_code == 404


@pytest.mark.mcp20251125
@pytest.mark.mcp_auth
@pytest.mark.mcp_optional
def test_path_based_protected_resource_endpoint_validates_path_shape(
    compliance_client,
    ensure_not_auth_error,
):
    # Invalid path shape should be rejected with 404 per router validation.
    response = compliance_client.get("/.well-known/oauth-protected-resource/not-a-valid-shape")
    ensure_not_auth_error(response)
    assert response.status_code == 404
