# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_ui_version.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration tests for /version and the Version tab in the Admin UI.
Author: Mihai Criveti
"""

# Future
from __future__ import annotations

# Standard
import base64
import os
from typing import Dict

# Set environment before imports
os.environ["MCPGATEWAY_A2A_ENABLED"] = "false"  # Disable A2A for UI tests

# Third-Party
import pytest
from starlette.testclient import TestClient

# First-Party
from mcpgateway.config import settings
from mcpgateway.main import app


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def test_client() -> TestClient:
    """Spin up the FastAPI test client once for the whole session with proper database setup."""
    import tempfile
    from _pytest.monkeypatch import MonkeyPatch
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    mp = MonkeyPatch()

    # Create temp SQLite file
    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    # Patch settings
    from mcpgateway.config import settings
    mp.setattr(settings, "database_url", url, raising=False)

    import mcpgateway.db as db_mod
    import mcpgateway.main as main_mod

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    mp.setattr(db_mod, "engine", engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(main_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(main_mod, "engine", engine, raising=False)

    # Create schema
    db_mod.Base.metadata.create_all(bind=engine)

    client = TestClient(app)
    yield client

    # Cleanup
    mp.undo()
    engine.dispose()
    os.close(fd)
    os.unlink(path)


@pytest.fixture()
def auth_headers() -> Dict[str, str]:
    """
    Build the auth headers expected by the gateway:

    *   Authorization:  Basic <base64(user:pw)>
    *   X-API-Key:       user:pw                     (plain text)
    """
    creds = f"{settings.basic_auth_user}:{settings.basic_auth_password}"
    basic_b64 = base64.b64encode(creds.encode()).decode()

    return {
        "Authorization": f"Basic {basic_b64}",
        "X-API-Key": creds,
    }


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
# def test_version_partial_html(test_client: TestClient, auth_headers: Dict[str, str]):
#     """
#     /version?partial=true must return an HTML fragment with core meta-info.
#     """
#     resp = test_client.get("/version?partial=true", headers=auth_headers)
#     assert resp.status_code == 200
#     assert "text/html" in resp.headers["content-type"]

#     html = resp.text
#     # Very loose sanity checks - we only care that it is an HTML fragment
#     # and that some well-known marker exists.
#     assert "<div" in html
#     assert "App:" in html or "Application:" in html


@pytest.mark.skipif(not settings.mcpgateway_ui_enabled, reason="Admin UI tests require MCPGATEWAY_UI_ENABLED=true")
def test_admin_ui_contains_version_tab(test_client: TestClient, auth_headers: Dict[str, str]):
    """The Admin dashboard must contain the "Version & Environment Info" tab."""
    resp = test_client.get("/admin", headers=auth_headers)
    assert resp.status_code == 200
    assert 'id="tab-version-info"' in resp.text
    assert "Version and Environment Info" in resp.text


# def test_version_partial_htmx_load(test_client: TestClient, auth_headers: Dict[str, str]):
#     """
#     A second call (mimicking an HTMX swap) should yield the same fragment.
#     """
#     resp = test_client.get("/version?partial=true", headers=auth_headers)
#     assert resp.status_code == 200

#     html = resp.text
#     assert "<div" in html
#     assert "App:" in html or "Application:" in html
