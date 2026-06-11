# -*- coding: utf-8 -*-
"""Tests for external OIDC bearer token API auth (issue #3567)."""

from mcpgateway.config import Settings


def test_sso_api_token_auth_disabled_by_default():
    s = Settings()
    assert s.sso_api_token_auth_enabled is False


def test_ssoprovider_has_api_auth_columns():
    from mcpgateway.db import SSOProvider

    cols = SSOProvider.__table__.columns.keys()
    assert "trusted_for_api_auth" in cols
    assert "api_audience" in cols
