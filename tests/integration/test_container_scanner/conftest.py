#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_container_scanner/conftest.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Agnetha

Shared fixtures for container scanner integration tests.
"""

from __future__ import annotations

# Third-Party
import pytest
from fastapi.testclient import TestClient

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.main import app
from mcpgateway.routers.container_scanner_router import container_scanner_router
from plugins.container_scanner.storage.repository import container_scan_repo

# Register the router if plugins were disabled at startup (e.g. in CI without config)
if not any(getattr(r, "path", "").startswith("/container-scanner") for r in app.routes):
    app.include_router(container_scanner_router)


@pytest.fixture
def clean_repo():
    """Clear the shared singleton before and after each test."""
    container_scan_repo.clear()
    yield container_scan_repo
    container_scan_repo.clear()


@pytest.fixture
def client(clean_repo):
    """TestClient with auth dependency overridden."""
    app.dependency_overrides[get_current_user] = lambda: {"email": "test@example.com", "is_admin": True}
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)
