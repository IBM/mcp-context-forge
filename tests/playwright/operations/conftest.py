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

# Local
from tests.helpers.auth import make_playwright_api_context, make_test_jwt

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8080")


def _make_jwt(email: str, is_admin: bool = False, teams=None) -> str:
    return make_test_jwt(email, is_admin=is_admin, teams=teams)


@pytest.fixture(scope="module")
def admin_api(playwright: Playwright) -> Generator[APIRequestContext, None, None]:
    """Admin-authenticated API context.

    Prefers the ``MCP_AUTH`` env var (set by the Makefile from a token signed with
    the running gateway's secret) so signatures match the deployed instance. Falls
    back to a locally-signed JWT only when ``MCP_AUTH`` is unset.
    """
    token = os.getenv("MCP_AUTH", "") or _make_jwt("admin@example.com", is_admin=True)
    ctx = make_playwright_api_context(playwright, BASE_URL, token)
    yield ctx
    ctx.dispose()


@pytest.fixture(scope="module")
def non_admin_api(playwright: Playwright) -> Generator[APIRequestContext, None, None]:
    """Non-admin API context for permission checks."""
    token = _make_jwt("nonadmin-ops@example.com", is_admin=False)
    ctx = make_playwright_api_context(playwright, BASE_URL, token)
    yield ctx
    ctx.dispose()
