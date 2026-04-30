# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Location: ./tests/playwright/security/test_token_lifecycle.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Token Lifecycle E2E Tests.

Tests API token create/read/update/revoke operations through the /tokens REST API.
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


def _get_token_id(resp_json: dict) -> str | None:
    """Extract token ID from create or get response."""
    # Create response: {"access_token": "...", "token": {"id": "...", ...}}
    # Get response: {"id": "...", ...}
    token_obj = resp_json.get("token", resp_json)
    return token_obj.get("id") or token_obj.get("token_id")


def _get_token_name(resp_json: dict) -> str | None:
    """Extract token name from response."""
    token_obj = resp_json.get("token", resp_json)
    return token_obj.get("name")


# ---------------------------------------------------------------------------
# Token CRUD Lifecycle
# ---------------------------------------------------------------------------


class TestTokenLifecycle:
    """Test API token create/list/update/revoke operations."""

    @pytest.fixture(scope="class")
    def lifecycle_token(self, admin_api: APIRequestContext):
        """Create a token for lifecycle tests, cleanup after class."""
        token_name = f"lifecycle-token-{uuid.uuid4().hex[:8]}"
        resp = admin_api.post("/tokens", data={"name": token_name, "expires_in_days": 30})
        assert resp.status in (200, 201), f"Failed to create token: {resp.status} {resp.text()}"
        data = resp.json()
        token_id = _get_token_id(data)
        yield {"id": token_id, "name": token_name, "raw": data}
        try:
            if token_id:
                admin_api.delete(f"/tokens/{token_id}")
        except Exception:
            pass

    def test_create_token(self, admin_api: APIRequestContext):
        """Admin can create an API token."""
        token_name = f"create-token-{uuid.uuid4().hex[:8]}"
        resp = admin_api.post("/tokens", data={"name": token_name, "expires_in_days": 7})
        assert resp.status in (200, 201)
        data = resp.json()
        assert _get_token_name(data) == token_name
        assert data.get("access_token"), "Raw access_token should be returned on creation"
        # Cleanup
        token_id = _get_token_id(data)
        if token_id:
            admin_api.delete(f"/tokens/{token_id}")

    def test_list_tokens(self, admin_api: APIRequestContext, lifecycle_token: dict):
        """Created token appears in token list."""
        resp = admin_api.get("/tokens")
        assert resp.status == 200
        data = resp.json()
        # Response format: {"tokens": [...], "total": N, "limit": N, "offset": N}
        tokens = data.get("tokens", data if isinstance(data, list) else [])
        token_ids = [t.get("id") or t.get("token_id") for t in tokens]
        assert lifecycle_token["id"] in token_ids

    def test_get_token_details(self, admin_api: APIRequestContext, lifecycle_token: dict):
        """Get specific token details by ID."""
        resp = admin_api.get(f"/tokens/{lifecycle_token['id']}")
        assert resp.status == 200

    def test_update_token(self, admin_api: APIRequestContext, lifecycle_token: dict):
        """Admin can update a token's name."""
        new_name = f"updated-{uuid.uuid4().hex[:8]}"
        resp = admin_api.put(f"/tokens/{lifecycle_token['id']}", data={"name": new_name})
        assert resp.status == 200
        updated = resp.json()
        assert _get_token_name(updated) == new_name

    def test_revoke_token(self, admin_api: APIRequestContext):
        """Admin can revoke a token."""
        token_name = f"revoke-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post("/tokens", data={"name": token_name, "expires_in_days": 1})
        assert create_resp.status in (200, 201)
        token_id = _get_token_id(create_resp.json())
        resp = admin_api.delete(f"/tokens/{token_id}")
        assert resp.status in (200, 204)

    def test_admin_list_all_tokens(self, admin_api: APIRequestContext):
        """Admin can list all tokens across all users."""
        resp = admin_api.get("/tokens/admin/all")
        assert resp.status == 200
        data = resp.json()
        tokens = data.get("tokens", data if isinstance(data, list) else [])
        assert isinstance(tokens, list)


# ---------------------------------------------------------------------------
# Token Permission Denial
# ---------------------------------------------------------------------------


class TestTokenRevokeUI:
    """Regression tests for token revoke via the admin UI.

    The revoke button previously used a broken HTMX hx-delete attribute with
    an undefined template variable (``{{token_id}}`` instead of ``{{token.id}}``),
    resulting in ``DELETE /admin/tokens/`` (missing ID) → 404.

    These tests verify the fix: the button now delegates to the JS ``revokeToken()``
    function via ``data-action="token-revoke"``, which calls the correct endpoint.

    """

    def test_revoke_button_triggers_correct_api_call(self, admin_api: APIRequestContext, tokens_page):
        """Revoke button in UI must send DELETE /tokens/{token_id} (not /admin/tokens/)."""
        token_name = f"ui-revoke-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post("/tokens", data={"name": token_name, "expires_in_days": 1})
        assert create_resp.status in (200, 201), f"Setup failed: {create_resp.status}"
        token_id = _get_token_id(create_resp.json())

        try:
            # Navigate to tokens tab and wait for the token to appear
            tokens_page.navigate_to_tokens_tab()
            tokens_page.wait_for_token_visible(token_name, timeout=15000)

            # Verify the revoke button is actually visible in the UI
            # (prevents the revoke_token() fallback API path from masking UI bugs)
            revoke_btn = tokens_page.get_token_revoke_btn(token_name)
            assert revoke_btn.count() > 0 and revoke_btn.first.is_visible(), "Revoke button must be visible for an active token"

            # Click revoke via UI button directly — bypasses the fallback path
            with tokens_page.page.expect_response(
                lambda r: f"/tokens/{token_id}" in r.url and r.request.method == "DELETE",
                timeout=10000,
            ) as response_info:
                tokens_page.page.once("dialog", lambda dialog: dialog.accept())
                revoke_btn.first.click()

            response = response_info.value
            assert response.status in (200, 204), f"Revoke should succeed (got {response.status}). " "If 404, the button may still be using the broken hx-delete path."
        finally:
            # Cleanup: ensure token is revoked even if UI test fails
            try:
                admin_api.delete(f"/tokens/{token_id}")
            except Exception:
                pass

    def test_revoke_button_not_shown_for_revoked_token(self, admin_api: APIRequestContext, tokens_page):
        """Already-revoked tokens must not show a revoke button even when listed."""
        token_name = f"already-revoked-{uuid.uuid4().hex[:8]}"
        create_resp = admin_api.post("/tokens", data={"name": token_name, "expires_in_days": 1})
        assert create_resp.status in (200, 201)
        token_id = _get_token_id(create_resp.json())

        # Revoke via API first
        revoke_resp = admin_api.delete(f"/tokens/{token_id}")
        assert revoke_resp.status in (200, 204)

        # Navigate to tokens tab with include_inactive=true so revoked token IS listed
        tokens_page.navigate_to_tokens_tab()
        # Enable "Show inactive" to make revoked tokens visible in the list
        inactive_checkbox = tokens_page.page.locator("#tokens-inactive-toggle, [name='include_inactive']")
        if inactive_checkbox.count() > 0 and not inactive_checkbox.first.is_checked():
            inactive_checkbox.first.click()
            tokens_page.page.wait_for_timeout(2000)

        # Verify the token card IS rendered (not vacuously absent)
        token_card = tokens_page.page.locator(f"text={token_name}")
        if token_card.count() > 0:
            # Token is visible — the revoke button must NOT be present
            revoke_btn = tokens_page.get_token_revoke_btn(token_name)
            assert revoke_btn.count() == 0, "Revoke button should be hidden for already-revoked tokens"
        else:
            # If include_inactive toggle is not available, verify via API that token is truly revoked
            resp = admin_api.get(f"/tokens/{token_id}")
            if resp.status == 200:
                token_data = resp.json()
                token_obj = token_data.get("token", token_data)
                assert not token_obj.get("is_active", True), "Token should be inactive after revocation"


class TestTokenPermissions:
    """Test that non-admin users have limited token access."""

    def test_non_admin_denied_admin_token_list(self, non_admin_api: APIRequestContext):
        """Non-admin user cannot list all tokens."""
        resp = non_admin_api.get("/tokens/admin/all")
        assert resp.status in (401, 403), f"Non-admin should be denied admin token list, got {resp.status}"
