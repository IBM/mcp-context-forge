# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Session security and CSRF-related tests for admin auth cookies."""

# Future
from __future__ import annotations

# Third-Party
import pytest

# First-Party
from mcpgateway.config import settings


def _expected_samesite() -> str:
    value = (settings.cookie_samesite or "lax").strip().lower()
    return {"lax": "Lax", "strict": "Strict", "none": "None"}.get(value, "Lax")


class TestSessionAndCSRFSecurity:
    """Session cookie hardening and CSRF protection expectations."""

    def test_admin_session_cookie_has_security_attributes(self, admin_page):
        if not settings.auth_required:
            pytest.skip("Authentication is disabled; session cookie hardening is not applicable.")

        page = admin_page.page
        jwt_cookie = next((cookie for cookie in page.context.cookies() if cookie["name"] == "jwt_token"), None)
        assert jwt_cookie is not None, "Expected jwt_token cookie after admin authentication"
        assert jwt_cookie["httpOnly"] is True
        assert jwt_cookie["sameSite"] == _expected_samesite()

    def test_logout_clears_session_cookie(self, admin_page):
        if not settings.auth_required:
            pytest.skip("Authentication is disabled; logout cookie clearing is not applicable.")

        page = admin_page.page
        before = next((cookie for cookie in page.context.cookies() if cookie["name"] == "jwt_token"), None)
        if before is None:
            pytest.skip("No jwt_token cookie present before logout in this environment.")

        response = page.request.post("/admin/logout")
        assert response.status in (200, 302, 303), f"Unexpected logout status: {response.status}"

        after = next((cookie for cookie in page.context.cookies() if cookie["name"] == "jwt_token"), None)
        assert after is None or not after.get("value"), "jwt_token cookie should be cleared by logout"

    @pytest.mark.xfail(
        reason="CSRF origin/token validation for admin form POSTs is not yet enforced server-side.",
        strict=False,
    )
    def test_cross_origin_state_change_without_csrf_token_is_rejected(self, admin_page):
        if not settings.auth_required:
            pytest.skip("Authentication is disabled; CSRF protections are not applicable.")

        page = admin_page.page
        response = page.request.post(
            "/admin/logout",
            headers={"Origin": "https://evil.example"},
        )
        assert response.status in (400, 403), f"Cross-origin POST should be rejected, got {response.status}"
