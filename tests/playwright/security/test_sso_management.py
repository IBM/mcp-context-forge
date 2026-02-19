# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""SSO Provider Management E2E Tests.

Tests SSO provider CRUD operations through the /auth/sso/admin REST API.
These tests are skipped if SSO endpoints are not available in the test environment.
"""

# Future
from __future__ import annotations

# Standard
import logging
import uuid

# Third-Party
from playwright.sync_api import APIRequestContext
import pytest

logger = logging.getLogger(__name__)

SSO_ADMIN_PATH = "/auth/sso/admin/providers"


def _make_provider_data(provider_id: str | None = None) -> dict:
    """Generate test SSO provider configuration."""
    pid = provider_id or f"test-sso-{uuid.uuid4().hex[:8]}"
    return {
        "id": pid,
        "name": pid,
        "display_name": "Test SSO Provider",
        "provider_type": "oidc",
        "client_id": "test-client-id",
        "client_secret": "test-client-secret",
        "authorization_url": "https://auth.example.com/authorize",
        "token_url": "https://auth.example.com/token",
        "userinfo_url": "https://auth.example.com/userinfo",
        "scope": "openid profile email",
    }


def _sso_available(admin_api: APIRequestContext) -> bool:
    """Check if SSO admin endpoints are available."""
    resp = admin_api.get(SSO_ADMIN_PATH)
    return resp.status != 404


# ---------------------------------------------------------------------------
# SSO Provider CRUD
# ---------------------------------------------------------------------------


class TestSSOProviderLifecycle:
    """Test SSO provider create/read/update/delete operations."""

    @pytest.fixture(autouse=True)
    def _skip_if_sso_unavailable(self, admin_api: APIRequestContext):
        """Skip all tests in this class if SSO endpoints are not available."""
        if not _sso_available(admin_api):
            pytest.skip("SSO admin endpoints not available in this environment")

    @pytest.fixture(scope="class")
    def sso_provider(self, admin_api: APIRequestContext):
        """Create an SSO provider for lifecycle tests, cleanup after class."""
        if not _sso_available(admin_api):
            pytest.skip("SSO admin endpoints not available in this environment")
        data = _make_provider_data()
        resp = admin_api.post(SSO_ADMIN_PATH, data=data)
        assert resp.status in (200, 201), f"Failed to create SSO provider: {resp.status} {resp.text()}"
        provider = resp.json()
        yield provider
        try:
            admin_api.delete(f"{SSO_ADMIN_PATH}/{data['id']}")
        except Exception:
            pass

    def test_create_sso_provider(self, admin_api: APIRequestContext):
        """Admin can create an OIDC SSO provider."""
        data = _make_provider_data()
        resp = admin_api.post(SSO_ADMIN_PATH, data=data)
        assert resp.status in (200, 201)
        # Cleanup
        admin_api.delete(f"{SSO_ADMIN_PATH}/{data['id']}")

    def test_list_sso_providers(self, admin_api: APIRequestContext, sso_provider: dict):
        """Admin can list all SSO providers."""
        resp = admin_api.get(SSO_ADMIN_PATH)
        assert resp.status == 200
        providers = resp.json()
        assert isinstance(providers, list)

    def test_update_sso_provider(self, admin_api: APIRequestContext, sso_provider: dict):
        """Admin can update an SSO provider's display name."""
        provider_id = sso_provider.get("id") or sso_provider.get("name")
        resp = admin_api.put(
            f"{SSO_ADMIN_PATH}/{provider_id}",
            data={"display_name": "Updated SSO Provider"},
        )
        assert resp.status == 200

    def test_delete_sso_provider(self, admin_api: APIRequestContext):
        """Admin can delete an SSO provider."""
        data = _make_provider_data()
        admin_api.post(SSO_ADMIN_PATH, data=data)
        resp = admin_api.delete(f"{SSO_ADMIN_PATH}/{data['id']}")
        assert resp.status in (200, 204)

    def test_non_admin_denied_sso_create(self, non_admin_api: APIRequestContext):
        """Non-admin user cannot create SSO providers."""
        data = _make_provider_data()
        resp = non_admin_api.post(SSO_ADMIN_PATH, data=data)
        assert resp.status in (401, 403), f"Non-admin should be denied, got {resp.status}"
