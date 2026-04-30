# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_ui_version.py
Copyright 2026
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

# Third-Party
import pytest
from starlette.testclient import TestClient

# First-Party
from mcpgateway.config import settings

# Note: mcpgateway.main is imported lazily inside test_client(), after the
# main_app_with_admin_api session fixture has reloaded it with the admin
# and UI flags flipped on.
#
# This file used to force ``MCPGATEWAY_A2A_ENABLED=false`` at module
# import time "to disable A2A for UI tests". Under xdist that assignment
# can fire on a worker before it first imports ``mcpgateway.main``,
# which then leaves ``a2a_router`` unmounted and breaks every downstream
# test that targets ``/a2a/*`` or an admin A2A handler. The only test
# in this file is ``@pytest.mark.skip``'d anyway, so the env poison is
# pure collection-time cost. Removed.


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def test_client(main_app_with_admin_api) -> TestClient:
    """Spin up the FastAPI test client once for the whole session with proper database setup."""
    # Standard
    import tempfile

    # Third-Party
    from _pytest.monkeypatch import MonkeyPatch
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    mp = MonkeyPatch()

    # Create temp SQLite file
    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    # Patch settings
    # First-Party
    from mcpgateway.config import settings

    mp.setattr(settings, "database_url", url, raising=False)

    # First-Party
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

    client = TestClient(main_app_with_admin_api)
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


@pytest.mark.skip("Auth system changed - needs update for email auth")
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
