# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""LLM Configuration E2E Tests.

Tests LLM provider and model management endpoints.
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


def _llm_config_available(admin_api: APIRequestContext) -> bool:
    """Check if LLM configuration endpoints are available."""
    resp = admin_api.get("/providers")
    return resp.status != 404


class TestLLMProviderLifecycle:
    """Test LLM provider CRUD lifecycle."""

    @pytest.fixture(autouse=True)
    def _skip_if_unavailable(self, admin_api: APIRequestContext):
        if not _llm_config_available(admin_api):
            pytest.skip("LLM configuration endpoints not available")

    def test_create_provider(self, admin_api: APIRequestContext):
        """Admin can create an LLM provider."""
        name = f"test-provider-{uuid.uuid4().hex[:8]}"
        resp = admin_api.post(
            "/providers",
            data={
                "name": name,
                "provider_type": "openai",
                "api_base": "https://api.openai.com/v1",
                "api_key": "sk-test-key-not-real",
            },
        )
        assert resp.status in (200, 201), f"Create provider failed: {resp.status} {resp.text()}"
        provider = resp.json()
        assert provider["name"] == name

        # Cleanup
        admin_api.delete(f"/providers/{provider['id']}")

    def test_list_providers(self, admin_api: APIRequestContext):
        """Admin can list LLM providers."""
        resp = admin_api.get("/providers")
        assert resp.status == 200

    def test_get_provider(self, admin_api: APIRequestContext):
        """Admin can get a specific provider."""
        name = f"get-provider-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post(
            "/providers",
            data={
                "name": name,
                "provider_type": "openai",
                "api_base": "https://api.openai.com/v1",
                "api_key": "sk-test-key-not-real",
            },
        )
        provider = create_resp.json()

        resp = admin_api.get(f"/providers/{provider['id']}")
        assert resp.status == 200
        fetched = resp.json()
        assert fetched["name"] == name

        admin_api.delete(f"/providers/{provider['id']}")

    def test_update_provider(self, admin_api: APIRequestContext):
        """Admin can update a provider."""
        name = f"update-provider-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post(
            "/providers",
            data={
                "name": name,
                "provider_type": "openai",
                "api_base": "https://api.openai.com/v1",
                "api_key": "sk-test-key-not-real",
            },
        )
        provider = create_resp.json()

        resp = admin_api.patch(f"/providers/{provider['id']}", data={"name": f"{name}-updated"})
        assert resp.status == 200
        updated = resp.json()
        assert updated["name"] == f"{name}-updated"

        admin_api.delete(f"/providers/{provider['id']}")

    def test_deactivate_provider(self, admin_api: APIRequestContext):
        """Admin can deactivate a provider."""
        name = f"deact-provider-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post(
            "/providers",
            data={
                "name": name,
                "provider_type": "openai",
                "api_base": "https://api.openai.com/v1",
                "api_key": "sk-test-key-not-real",
            },
        )
        provider = create_resp.json()

        resp = admin_api.post(f"/providers/{provider['id']}/state?activate=false")
        assert resp.status == 200

        admin_api.delete(f"/providers/{provider['id']}")

    def test_delete_provider(self, admin_api: APIRequestContext):
        """Admin can delete a provider."""
        name = f"del-provider-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post(
            "/providers",
            data={
                "name": name,
                "provider_type": "openai",
                "api_base": "https://api.openai.com/v1",
                "api_key": "sk-test-key-not-real",
            },
        )
        provider = create_resp.json()

        resp = admin_api.delete(f"/providers/{provider['id']}")
        assert resp.status in (200, 204)

    def test_non_admin_cannot_manage_providers(self, non_admin_api: APIRequestContext):
        """Non-admin user is denied provider management."""
        resp = non_admin_api.get("/providers")
        assert resp.status in (401, 403), f"Non-admin provider access should be denied, got {resp.status}"


class TestGatewayModels:
    """Test public gateway models endpoint."""

    @pytest.fixture(autouse=True)
    def _skip_if_unavailable(self, admin_api: APIRequestContext):
        if not _llm_config_available(admin_api):
            pytest.skip("LLM configuration endpoints not available")

    def test_list_gateway_models(self, admin_api: APIRequestContext):
        """Authenticated user can list available gateway models."""
        resp = admin_api.get("/gateway/models")
        assert resp.status == 200
        data = resp.json()
        assert isinstance(data, dict)
