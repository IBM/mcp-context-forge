# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Location: ./tests/playwright/security/test_session_csrf_security.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Session security and CSRF-related tests for admin auth cookies.
"""

# Future
from __future__ import annotations

# Standard
from urllib.parse import urlparse

# Third-Party
import pytest

# First-Party
from mcpgateway.admin import ADMIN_CSRF_COOKIE_NAME, ADMIN_CSRF_HEADER_NAME
from mcpgateway.config import settings


def _expected_samesite() -> str:
    value = (settings.cookie_samesite or "lax").strip().lower()
    return {"lax": "Lax", "strict": "Strict", "none": "None"}.get(value, "Lax")


class TestSessionAndCSRFSecurity:
    """Session cookie hardening and CSRF protection expectations."""

    @staticmethod
    def _logout_headers(page) -> dict[str, str]:
        """Build CSRF/origin headers for logout mutation requests."""
        headers: dict[str, str] = {}
        csrf_cookie = next((cookie for cookie in page.context.cookies() if cookie["name"] == ADMIN_CSRF_COOKIE_NAME), None)
        if csrf_cookie and csrf_cookie.get("value"):
            headers[ADMIN_CSRF_HEADER_NAME] = csrf_cookie["value"]

        parsed = urlparse(page.url or "")
        if parsed.scheme and parsed.netloc:
            origin = f"{parsed.scheme}://{parsed.netloc}"
            headers["Origin"] = origin
            headers["Referer"] = f"{origin}/admin"

        return headers

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

        response = page.request.post("/admin/logout", headers=self._logout_headers(page))
        assert response.status in (200, 302, 303), f"Unexpected logout status: {response.status}"

        after = next((cookie for cookie in page.context.cookies() if cookie["name"] == "jwt_token"), None)
        assert after is None or not after.get("value"), "jwt_token cookie should be cleared by logout"

    def test_cross_origin_state_change_without_csrf_token_is_rejected(self, admin_page):
        if not settings.auth_required:
            pytest.skip("Authentication is disabled; CSRF protections are not applicable.")

        page = admin_page.page
        response = page.request.post(
            "/admin/logout",
            headers={"Origin": "https://evil.example"},
        )
        assert response.status in (400, 403), f"Cross-origin POST should be rejected, got {response.status}"


def _is_csrf_rejection(status: int, body: str) -> bool:
    """Return True when a response was rejected by either CSRF layer.

    ``CSRFMiddleware`` answers 403 with ``{"detail": "CSRF validation failed",
    "code": "CSRF_TOKEN_INVALID"}``; ``enforce_admin_csrf`` raises ``HTTPException(403)``
    with a detail containing "CSRF". An RBAC 403 from ``@require_permission`` is not a
    CSRF rejection and must not be counted as one.

    Args:
        status: HTTP status code of the response.
        body: Raw response body text.

    Returns:
        True if this is a CSRF rejection.
    """
    return status == 403 and ("CSRF_TOKEN_INVALID" in body or "CSRF" in body)


@pytest.fixture
def freshly_logged_in_page(page, base_url):
    """A browser context logged in via the real form, with the dashboard NOT loaded.

    The window between ``POST /admin/login`` and the first ``/admin/`` load is the whole
    subject of #5978, so this fixture must not navigate to the dashboard — ``admin_ui()``
    rotates the CSRF cookie to its HMAC-bound value and the divergence disappears. It
    also cannot use ``_ensure_admin_logged_in``, which injects the JWT cookie directly
    and so never exercises ``admin_login_handler`` at all.

    ``max_redirects=0`` keeps the 303 from being followed into the dashboard while still
    storing the cookies the login response set.

    Args:
        page: Playwright page (supplies the browser context cookie jar).
        base_url: Gateway base URL.

    Yields:
        The Page, holding a freshly-issued, un-rotated admin session.
    """
    # First-Party
    from tests.playwright.conftest import ADMIN_ACTIVE_PASSWORD, ADMIN_EMAIL

    response = page.request.post(
        f"{base_url}/admin/login",
        form={"email": ADMIN_EMAIL, "password": ADMIN_ACTIVE_PASSWORD[0]},
        max_redirects=0,
    )
    if response.status != 303:
        pytest.skip(f"admin form login did not redirect as expected (status {response.status}); cannot test the pre-dashboard window")

    location = response.headers.get("location", "")
    if "change-password-required" in location:
        pytest.skip("admin user requires a password change; the login redirect does not reach the tested flow")

    yield page


class TestAdminCsrfMountParity:
    """`/admin/**` and `/v1/admin/**` must enforce identical CSRF requirements (#5978)."""

    WRITE_PATH = "/admin/llm/providers/e2e-nonexistent-provider/state"

    @staticmethod
    def _csrf_headers(page, base_url: str) -> dict[str, str]:
        """Build cookie-derived CSRF headers for an admin write.

        Args:
            page: Playwright page whose context holds the session cookies.
            base_url: Gateway base URL, used as the Origin.

        Returns:
            Header dict carrying the CSRF token, Origin and Referer.
        """
        csrf_cookie = next((c for c in page.context.cookies() if c["name"] == ADMIN_CSRF_COOKIE_NAME), None)
        assert csrf_cookie and csrf_cookie.get("value"), "login must set the admin CSRF cookie"
        return {
            ADMIN_CSRF_HEADER_NAME: csrf_cookie["value"],
            "Origin": base_url,
            "Referer": f"{base_url}/admin/",
        }

    def test_write_agrees_across_mounts_immediately_after_login(self, freshly_logged_in_page, base_url):
        """Both mounts must accept the same cookie/header pair before any dashboard load.

        Before #5978 was fixed, the `/admin/llm` write reached the handler while the
        identical `/v1/admin/llm` write was rejected by CSRFMiddleware with 403
        CSRF_TOKEN_INVALID, because the login cookie was an unbound opaque token.
        """
        if not settings.auth_required:
            pytest.skip("Authentication is disabled; CSRF protections are not applicable.")

        page = freshly_logged_in_page
        headers = self._csrf_headers(page, base_url)

        results = {}
        for mount in ("", "/v1"):
            response = page.request.post(f"{base_url}{mount}{self.WRITE_PATH}", headers=headers)
            results[mount or "legacy"] = (response.status, response.text())

        for mount, (status, body) in results.items():
            assert not _is_csrf_rejection(status, body), f"{mount} mount was rejected by CSRF: {status} {body[:300]}"
        assert results["legacy"][0] == results["/v1"][0], f"mounts disagree on status: {[(m, s) for m, (s, _) in results.items()]}"

    def test_write_agrees_across_mounts_after_dashboard_rotation(self, freshly_logged_in_page, base_url):
        """Parity must also hold once the dashboard has rotated the CSRF cookie.

        This half passed before #5978 was fixed; it is the control proving the fix did
        not change post-rotation behaviour.
        """
        if not settings.auth_required:
            pytest.skip("Authentication is disabled; CSRF protections are not applicable.")

        page = freshly_logged_in_page
        page.goto(f"{base_url}/admin/")  # admin_ui() re-mints the JWT and rotates the CSRF cookie

        headers = self._csrf_headers(page, base_url)

        legacy = page.request.post(f"{base_url}{self.WRITE_PATH}", headers=headers)
        versioned = page.request.post(f"{base_url}/v1{self.WRITE_PATH}", headers=headers)

        assert not _is_csrf_rejection(legacy.status, legacy.text())
        assert not _is_csrf_rejection(versioned.status, versioned.text())
        assert legacy.status == versioned.status

    def test_write_without_csrf_header_is_rejected_on_both_mounts(self, freshly_logged_in_page, base_url):
        """Deny-path: omitting X-CSRF-Token must be rejected identically on both mounts.

        Guards against "fixing" parity by weakening the versioned mount.
        """
        if not settings.auth_required:
            pytest.skip("Authentication is disabled; CSRF protections are not applicable.")

        page = freshly_logged_in_page
        headers = {"Origin": base_url, "Referer": f"{base_url}/admin/"}

        legacy = page.request.post(f"{base_url}{self.WRITE_PATH}", headers=headers)
        versioned = page.request.post(f"{base_url}/v1{self.WRITE_PATH}", headers=headers)

        assert legacy.status == 403, f"legacy mount must reject a write with no CSRF token, got {legacy.status}"
        assert versioned.status == 403, f"versioned mount must reject a write with no CSRF token, got {versioned.status}"
