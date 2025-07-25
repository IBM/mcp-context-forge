# -*- coding: utf-8 -*-
"""
Integration tests for /version and the Version tab in the Admin UI.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Author: Mihai Criveti
"""

# Future
from __future__ import annotations

# Standard
import base64
from typing import Dict

# Third‑Party
import pytest
from starlette.testclient import TestClient

# First‑Party
from mcpgateway.config import settings


# ──────────────────────────────────────────────
# Fixtures (local to this test file)
# ──────────────────────────────────────────────
@pytest.fixture(scope="module")
def test_client(app_with_temp_db) -> TestClient:
    """
    Build a TestClient against the FastAPI app that
    app_with_temp_db returns (i.e. the one wired to
    the temporary SQLite database).
    """
    return TestClient(app_with_temp_db)


@pytest.fixture()
def auth_headers() -> Dict[str, str]:
    creds = f"{settings.basic_auth_user}:{settings.basic_auth_password}"
    basic_b64 = base64.b64encode(creds.encode()).decode()
    return {
        "Authorization": f"Basic {basic_b64}",
        "X-API-Key": creds,
    }


# ──────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────
@pytest.mark.skipif(
    not settings.mcpgateway_ui_enabled,
    reason="Admin UI tests require MCPGATEWAY_UI_ENABLED=true",
)
def test_admin_ui_contains_version_tab(test_client: TestClient, auth_headers: Dict[str, str]):
    """
    The Admin dashboard must contain the "Version & Environment Info" tab.
    """
    resp = test_client.get("/admin", headers=auth_headers)
    assert resp.status_code == 200
    assert 'id="tab-version-info"' in resp.text
    assert "Version and Environment Info" in resp.text
