# -*- coding: utf-8 -*-
"""
Integration tests for /version and the Version tab in the Admin UI.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Author: Mihai Criveti
"""

import base64

import pytest
from fastapi.testclient import TestClient

from mcpgateway.config import settings  # pulls credentials from config
from mcpgateway.main import app  # FastAPI application instance

# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def test_client() -> TestClient:
    """Provide a live TestClient for the FastAPI app."""
    with TestClient(app) as client:
        yield client


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """
    Build a Basic-Auth header from *current* config settings so the tests keep
    working even if credentials change via environment variables or .env file.
    """
    raw = f"{settings.basic_auth_user}:{settings.basic_auth_password}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #


def test_version_partial_html(test_client: TestClient, auth_headers: dict):
    """
    /version?partial=true must return an HTML fragment with core meta-info.
    """
    resp = test_client.get("/version?partial=true", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")

    html = resp.text
    assert "<div" in html  # fragment is wrapped in a div
    assert "App:" in html  # application metadata present


def test_admin_ui_contains_version_tab(test_client: TestClient, auth_headers: dict):
    """
    Full Admin UI should expose the Version & Environment tab stub.
    """
    resp = test_client.get("/admin", headers=auth_headers)
    assert resp.status_code == 200
    page = resp.text
    assert 'id="tab-version-info"' in page
    assert "Version and Environment Info" in page


@pytest.mark.parametrize("hx_request", [False, True])
def test_version_partial_htmx_load(
    test_client: TestClient,
    auth_headers: dict,
    hx_request: bool,
):
    """
    HTMX-initiated and normal GETs should return the same HTML fragment.
    """
    headers = auth_headers.copy()
    if hx_request:
        headers["HX-Request"] = "true"  # header HTMX automatically adds

    resp = test_client.get("/version?partial=true", headers=headers)
    assert resp.status_code == 200

    fragment = resp.text
    assert "<div" in fragment
    assert "App:" in fragment
