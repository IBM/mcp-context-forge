# -*- coding: utf-8 -*-
# Copyright (c) 2025 ContextForge Contributors.
# SPDX-License-Identifier: Apache-2.0

"""Location: ./tests/playwright/operations/conftest.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Shared fixtures for operations E2E tests.
"""

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


def _make_jwt(email: str, is_admin: bool = False, teams=None) -> str:
    return _create_jwt_token(
        {"sub": email},
        user_data={"email": email, "is_admin": is_admin, "auth_provider": "local"},
        teams=teams,
    )


@pytest.fixture(scope="module")
def admin_api(playwright: Playwright) -> Generator[APIRequestContext, None, None]:
    """Admin-authenticated API context.

    Prefers the ``MCP_AUTH`` env var (set by the Makefile from a token signed with
    the running gateway's secret) so signatures match the deployed instance. Falls
    back to a locally-signed JWT only when ``MCP_AUTH`` is unset.
    """
    token = os.getenv("MCP_AUTH", "") or _make_jwt("admin@example.com", is_admin=True)
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
