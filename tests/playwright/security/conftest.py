# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Shared fixtures for security E2E tests."""

# Future
from __future__ import annotations

# Standard
import logging
import os
from typing import Generator
import uuid

# Third-Party
from playwright.sync_api import APIRequestContext, Playwright
import pytest

# First-Party
from mcpgateway.utils.create_jwt_token import _create_jwt_token

logger = logging.getLogger(__name__)

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8080")
TEST_PASSWORD = "SecureTestPass123!"


_UNSET = object()


def _make_jwt(email: str, is_admin: bool = False, teams=_UNSET) -> str:
    """Create a JWT token for testing.

    Admin bypass requires ``teams: null`` in the JWT (not missing).
    """
    data: dict = {"sub": email}
    if teams is not _UNSET:
        return _create_jwt_token(data, user_data={"email": email, "is_admin": is_admin, "auth_provider": "local"}, teams=teams)
    if is_admin:
        data["teams"] = None
    return _create_jwt_token(data, user_data={"email": email, "is_admin": is_admin, "auth_provider": "local"})


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
def temp_user(admin_api: APIRequestContext):
    """Create a temporary test user, yield email, then delete."""
    email = f"test-{uuid.uuid4().hex[:8]}@example.com"
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
