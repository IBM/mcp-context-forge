# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Location: ./tests/playwright/security/conftest.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Shared fixtures for security E2E tests.
"""

# Future
from __future__ import annotations

# Standard
import logging
import os
import re
from typing import Generator
import uuid

# Third-Party
from playwright.sync_api import APIRequestContext, FrameLocator, Page, Playwright, Route
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
import pytest

# First-Party
from mcpgateway.utils.create_jwt_token import _create_jwt_token

# Local
from ..conftest import _ensure_admin_logged_in

logger = logging.getLogger(__name__)

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8080")
TEST_PASSWORD = "SecureTestPass123!"


def _make_jwt(email: str, is_admin: bool = False, teams=None) -> str:
    """Create a JWT token for testing."""
    return _create_jwt_token(
        {"sub": email},
        user_data={"email": email, "is_admin": is_admin, "auth_provider": "local"},
        teams=teams,
    )


@pytest.fixture(scope="module")
def admin_api(playwright: Playwright) -> Generator[APIRequestContext, None, None]:
    """Admin-authenticated API context for security tests."""
    token = _make_jwt("admin@example.com", is_admin=True)
    ctx = playwright.request.new_context(
        base_url=BASE_URL,
        extra_http_headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    yield ctx
    ctx.dispose()


@pytest.fixture(scope="module")
def non_admin_api(playwright: Playwright) -> Generator[APIRequestContext, None, None]:
    """Non-admin API context for permission denial tests."""
    token = _make_jwt("nonadmin-security@example.com", is_admin=False, teams=[])
    ctx = playwright.request.new_context(
        base_url=BASE_URL,
        extra_http_headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    yield ctx
    ctx.dispose()


@pytest.fixture(scope="module")
def anon_api(playwright: Playwright) -> Generator[APIRequestContext, None, None]:
    """Unauthenticated API context."""
    ctx = playwright.request.new_context(
        base_url=BASE_URL,
        extra_http_headers={"Accept": "application/json"},
    )
    yield ctx
    ctx.dispose()


@pytest.fixture
def iframe_host(page: Page, base_url: str):
    """Load admin inside an iframe, stripping X-Frame-Options/CSP restrictions.

    Returns a tuple of (frame_locator, frame_object) for interacting with
    the embedded admin.
    """
    _ensure_admin_logged_in(page, base_url)

    def _strip_headers(route: Route) -> None:
        try:
            response = route.fetch()
            headers = dict(response.headers)
            headers.pop("x-frame-options", None)
            if "content-security-policy" in headers:
                headers["content-security-policy"] = headers["content-security-policy"].replace("frame-ancestors 'none'", "frame-ancestors 'self'")
            route.fulfill(status=response.status, headers=headers, body=response.body())
        except Exception:
            pass

    admin_pattern = re.compile(r".*/admin.*")
    page.route(admin_pattern, _strip_headers)

    admin_url = f"{base_url}/admin/"
    page.set_content(f"""<!DOCTYPE html>
<html><head><title>iframe host</title></head>
<body style="margin:0;padding:0">
<iframe id="admin-frame"
        src="{admin_url}"
        style="width:100%;height:100vh;border:none"
        sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals">
</iframe>
</body></html>""")

    frame = page.frame_locator("#admin-frame")
    try:
        frame.locator('[data-testid="servers-tab"]').wait_for(state="visible", timeout=30000)
    except PlaywrightTimeoutError:
        pass  # CI may be slower; tests will assert individually

    yield frame

    page.unroute(admin_pattern)


@pytest.fixture
def temp_user(admin_api: APIRequestContext):
    """Create a temporary test user, yield email, then delete."""
    email = f"test-{uuid.uuid4().hex[:8]}@example.com"
    resp = admin_api.post(
        "/auth/email/admin/users",
        data={"email": email, "password": TEST_PASSWORD, "full_name": "Temp Test User"},
    )
    if resp.status == 401:
        # Transient auth race — retry once
        import time

        time.sleep(0.5)
        resp = admin_api.post(
            "/auth/email/admin/users",
            data={"email": email, "password": TEST_PASSWORD, "full_name": "Temp Test User"},
        )
    assert resp.status in (200, 201), f"Failed to create temp user: {resp.status}"
    yield email
    try:
        admin_api.delete(f"/auth/email/admin/users/{email}")
    except Exception:
        pass
