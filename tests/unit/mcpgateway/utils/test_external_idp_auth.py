# -*- coding: utf-8 -*-
"""Tests for external OIDC bearer token API auth (issue #3567)."""

# First-Party
from mcpgateway.config import Settings


def test_sso_api_token_auth_disabled_by_default():
    s = Settings()
    assert s.sso_api_token_auth_enabled is False


def test_ssoprovider_has_api_auth_columns():
    # First-Party
    from mcpgateway.db import SSOProvider

    cols = SSOProvider.__table__.columns.keys()
    assert "trusted_for_api_auth" in cols
    assert "api_audience" in cols


def test_sso_provider_schema_exposes_api_auth_fields():
    # First-Party
    from mcpgateway.routers.sso import SSOProviderCreateRequest, SSOProviderUpdateRequest

    assert "trusted_for_api_auth" in SSOProviderCreateRequest.model_fields
    assert "api_audience" in SSOProviderCreateRequest.model_fields
    assert "trusted_for_api_auth" in SSOProviderUpdateRequest.model_fields
    assert "api_audience" in SSOProviderUpdateRequest.model_fields


def test_api_trust_requires_audience_on_create():
    # Third-Party
    import pytest

    # First-Party
    from mcpgateway.routers.sso import SSOProviderCreateRequest

    with pytest.raises(ValueError, match="api_audience is required"):
        SSOProviderCreateRequest(
            id="kc",
            name="kc",
            display_name="KC",
            provider_type="oidc",
            client_id="c",
            client_secret="s",
            authorization_url="https://idp/authorize",
            token_url="https://idp/token",
            userinfo_url="https://idp/userinfo",
            trusted_for_api_auth=True,
            api_audience=None,
        )


def test_api_trust_requires_audience_on_update():
    # Third-Party
    import pytest

    # First-Party
    from mcpgateway.routers.sso import SSOProviderUpdateRequest

    with pytest.raises(ValueError, match="api_audience is required"):
        SSOProviderUpdateRequest(trusted_for_api_auth=True, api_audience=None)


def test_api_trust_with_audience_succeeds():
    # First-Party
    from mcpgateway.routers.sso import SSOProviderCreateRequest

    req = SSOProviderCreateRequest(
        id="kc",
        name="kc",
        display_name="KC",
        provider_type="oidc",
        client_id="c",
        client_secret="s",
        authorization_url="https://idp/authorize",
        token_url="https://idp/token",
        userinfo_url="https://idp/userinfo",
        trusted_for_api_auth=True,
        api_audience="api://my-api",
    )
    assert req.api_audience == "api://my-api"
