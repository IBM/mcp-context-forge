# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Shared fixtures for operations E2E tests."""

# Future
from __future__ import annotations

# Standard
import os
from typing import Generator

# Third-Party
from playwright.sync_api import APIRequestContext, Playwright
import pytest

# First-Party
from mcpgateway.utils.create_jwt_token import _create_jwt_token

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8080")


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
    """Admin-authenticated API context."""
    token = _make_jwt("admin@example.com", is_admin=True)
    ctx = playwright.request.new_context(
        base_url=BASE_URL,
        extra_http_headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    yield ctx
    ctx.dispose()


@pytest.fixture(scope="module")
def non_admin_api(playwright: Playwright) -> Generator[APIRequestContext, None, None]:
    """Non-admin API context for permission checks."""
    token = _make_jwt("nonadmin-ops@example.com", is_admin=False)
    ctx = playwright.request.new_context(
        base_url=BASE_URL,
        extra_http_headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    yield ctx
    ctx.dispose()
