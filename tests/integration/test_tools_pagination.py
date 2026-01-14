# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_tools_pagination.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Integration tests for Tools API pagination.
Tests verify that the /admin/tools endpoint properly implements pagination
with correct metadata, links, and team-based access control.
"""

# Standard
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock

# Third-Party
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from _pytest.monkeypatch import MonkeyPatch

# First-Party
from mcpgateway.auth import get_current_user
from mcpgateway.db import Tool as DbTool
from mcpgateway.main import app
from mcpgateway.utils.verify_credentials import require_auth
from mcpgateway.middleware.rbac import get_current_user_with_permissions, get_db as rbac_get_db

# Local
from tests.utils.rbac_mocks import patch_rbac_decorators, restore_rbac_decorators


@pytest.fixture
def test_db_and_client():
    """Create a test database and FastAPI TestClient with auth overrides."""
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

    def override_get_db():
        """Override database dependency."""
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[rbac_get_db] = override_get_db

    # Patch RBAC decorators to bypass permission checks
    rbac_originals = patch_rbac_decorators()

    yield TestSessionLocal, engine

    # Cleanup
    app.dependency_overrides.pop(rbac_get_db, None)
    restore_rbac_decorators(rbac_originals)
    mp.undo()
    engine.dispose()
    os.close(fd)
    os.unlink(path)


def create_user_context(email: str, is_admin: bool = False, TestSessionLocal=None):
    """Create a mock user context for testing."""

    async def mock_user_with_permissions():
        """Mock user context for RBAC."""
        return {
            "email": email,
            "full_name": f"Test User {email}",
            "is_admin": is_admin,
            "ip_address": "127.0.0.1",
            "user_agent": "test-client",
            "db": TestSessionLocal() if TestSessionLocal else None,
        }

    return mock_user_with_permissions


class TestToolsPagination:
    """Integration tests for Tools API pagination."""

    def test_tools_pagination_first_page(self, test_db_and_client):
        """Test pagination returns correct first page with metadata."""
        TestSessionLocal, _ = test_db_and_client
        db = TestSessionLocal()

        # Create test tools
        for i in range(25):
            tool = DbTool(
                id=f"tool-{i}",
                original_name=f"Tool {i}",
                custom_name=f"Tool {i}",
                url=f"http://test.com/tool{i}",
                description=f"Test tool {i}",
                input_schema={"type": "object"},
                enabled=True,
                owner_email="admin@example.com",
                visibility="public",
            )
            db.add(tool)
        db.commit()
        db.close()

        # Set up user context
        mock_user = MagicMock()
        mock_user.email = "admin@example.com"

        app.dependency_overrides[require_auth] = lambda: "admin@example.com"
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_current_user_with_permissions] = create_user_context("admin@example.com", TestSessionLocal=TestSessionLocal)

        client = TestClient(app)

        # Request first page with 10 items
        response = client.get("/admin/tools?page=1&per_page=10", headers={"Authorization": "Bearer test-token"})

        # Verify response
        assert response.status_code == 200
        data = response.json()

        # Verify data structure
        assert "data" in data
        assert "pagination" in data
        assert "links" in data

        # Verify pagination metadata
        assert data["pagination"]["page"] == 1
        assert data["pagination"]["per_page"] == 10
        assert data["pagination"]["total_items"] == 25
        assert data["pagination"]["total_pages"] == 3
        assert data["pagination"]["has_next"] is True
        assert data["pagination"]["has_prev"] is False

        # Verify data
        assert len(data["data"]) == 10
        assert all(isinstance(tool, dict) for tool in data["data"])

        # Verify links
        assert "/admin/tools?page=1" in data["links"]["self"]
        assert "/admin/tools?page=1" in data["links"]["first"]
        assert "/admin/tools?page=3" in data["links"]["last"]
        assert "/admin/tools?page=2" in data["links"]["next"]
        assert data["links"]["prev"] is None

        # Cleanup
        app.dependency_overrides.clear()

    def test_tools_pagination_middle_page(self, test_db_and_client):
        """Test pagination returns correct middle page."""
        TestSessionLocal, _ = test_db_and_client
        db = TestSessionLocal()

        # Create test tools
        for i in range(50):
            tool = DbTool(
                id=f"tool-{i}",
                original_name=f"Tool {i}",
                custom_name=f"Tool {i}",
                url=f"http://test.com/tool{i}",
                description=f"Test tool {i}",
                input_schema={"type": "object"},
                enabled=True,
                owner_email="admin@example.com",
                visibility="public",
            )
            db.add(tool)
        db.commit()
        db.close()

        # Set up user context
        mock_user = MagicMock()
        mock_user.email = "admin@example.com"

        app.dependency_overrides[require_auth] = lambda: "admin@example.com"
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_current_user_with_permissions] = create_user_context("admin@example.com", TestSessionLocal=TestSessionLocal)

        client = TestClient(app)

        # Request middle page
        response = client.get("/admin/tools?page=2&per_page=10", headers={"Authorization": "Bearer test-token"})

        # Verify response
        assert response.status_code == 200
        data = response.json()

        # Verify pagination metadata
        assert data["pagination"]["page"] == 2
        assert data["pagination"]["has_next"] is True
        assert data["pagination"]["has_prev"] is True

        # Verify links
        assert "/admin/tools?page=3" in data["links"]["next"]
        assert "/admin/tools?page=1" in data["links"]["prev"]

        # Cleanup
        app.dependency_overrides.clear()

    def test_tools_pagination_last_page(self, test_db_and_client):
        """Test pagination returns correct last page."""
        TestSessionLocal, _ = test_db_and_client
        db = TestSessionLocal()

        # Create 25 tools (3 pages of 10, last page has 5)
        for i in range(25):
            tool = DbTool(
                id=f"tool-{i}",
                original_name=f"Tool {i}",
                custom_name=f"Tool {i}",
                url=f"http://test.com/tool{i}",
                description=f"Test tool {i}",
                input_schema={"type": "object"},
                enabled=True,
                owner_email="admin@example.com",
                visibility="public",
            )
            db.add(tool)
        db.commit()
        db.close()

        # Set up user context
        mock_user = MagicMock()
        mock_user.email = "admin@example.com"

        app.dependency_overrides[require_auth] = lambda: "admin@example.com"
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_current_user_with_permissions] = create_user_context("admin@example.com", TestSessionLocal=TestSessionLocal)

        client = TestClient(app)

        # Request last page
        response = client.get("/admin/tools?page=3&per_page=10", headers={"Authorization": "Bearer test-token"})

        # Verify response
        assert response.status_code == 200
        data = response.json()

        # Verify pagination metadata
        assert data["pagination"]["page"] == 3
        assert data["pagination"]["has_next"] is False
        assert data["pagination"]["has_prev"] is True

        # Verify partial page (5 items on last page)
        assert len(data["data"]) == 5

        # Verify links
        assert data["links"]["next"] is None
        assert "/admin/tools?page=2" in data["links"]["prev"]

        # Cleanup
        app.dependency_overrides.clear()

    def test_tools_pagination_empty_result(self, test_db_and_client):
        """Test pagination with no tools returns empty result."""
        TestSessionLocal, _ = test_db_and_client

        # Set up user context (no tools created)
        mock_user = MagicMock()
        mock_user.email = "admin@example.com"

        app.dependency_overrides[require_auth] = lambda: "admin@example.com"
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_current_user_with_permissions] = create_user_context("admin@example.com", TestSessionLocal=TestSessionLocal)

        client = TestClient(app)

        # Request first page
        response = client.get("/admin/tools?page=1&per_page=10", headers={"Authorization": "Bearer test-token"})

        # Verify response
        assert response.status_code == 200
        data = response.json()

        # Verify empty data
        assert len(data["data"]) == 0
        assert data["pagination"]["total_items"] == 0
        assert data["pagination"]["total_pages"] == 0
        assert data["pagination"]["has_next"] is False
        assert data["pagination"]["has_prev"] is False

        # Cleanup
        app.dependency_overrides.clear()

    def test_tools_pagination_with_inactive_filter(self, test_db_and_client):
        """Test pagination with include_inactive filter."""
        TestSessionLocal, _ = test_db_and_client
        db = TestSessionLocal()

        # Create tools (mix of active and inactive)
        for i in range(20):
            tool = DbTool(
                id=f"tool-{i}",
                original_name=f"Tool {i}",
                custom_name=f"Tool {i}",
                url=f"http://test.com/tool{i}",
                description=f"Test tool {i}",
                input_schema={"type": "object"},
                enabled=(i % 2 == 0),  # Even: enabled, Odd: disabled
                owner_email="admin@example.com",
                visibility="public",
            )
            db.add(tool)
        db.commit()
        db.close()

        # Set up user context
        mock_user = MagicMock()
        mock_user.email = "admin@example.com"

        app.dependency_overrides[require_auth] = lambda: "admin@example.com"
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_current_user_with_permissions] = create_user_context("admin@example.com", TestSessionLocal=TestSessionLocal)

        client = TestClient(app)

        # Request without filter (should get 10 enabled tools)
        response = client.get("/admin/tools?page=1&per_page=50", headers={"Authorization": "Bearer test-token"})
        assert response.status_code == 200
        data_active_only = response.json()
        assert data_active_only["pagination"]["total_items"] == 10

        # Request with include_inactive (should get all 20 tools)
        response = client.get("/admin/tools?page=1&per_page=50&include_inactive=true", headers={"Authorization": "Bearer test-token"})
        assert response.status_code == 200
        data_all = response.json()
        assert data_all["pagination"]["total_items"] == 20

        # Cleanup
        app.dependency_overrides.clear()

    def test_tools_pagination_page_size_limits(self, test_db_and_client):
        """Test pagination enforces page size limits."""
        TestSessionLocal, _ = test_db_and_client
        db = TestSessionLocal()

        # Create test tools
        for i in range(10):
            tool = DbTool(
                id=f"tool-{i}",
                original_name=f"Tool {i}",
                custom_name=f"Tool {i}",
                url=f"http://test.com/tool{i}",
                description=f"Test tool {i}",
                input_schema={"type": "object"},
                enabled=True,
                owner_email="admin@example.com",
                visibility="public",
            )
            db.add(tool)
        db.commit()
        db.close()

        # Set up user context
        mock_user = MagicMock()
        mock_user.email = "admin@example.com"

        app.dependency_overrides[require_auth] = lambda: "admin@example.com"
        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_current_user_with_permissions] = create_user_context("admin@example.com", TestSessionLocal=TestSessionLocal)

        client = TestClient(app)

        # Test that oversized per_page returns validation error (422)
        # FastAPI validates Query parameters with le=500 at router level
        response = client.get("/admin/tools?page=1&per_page=10000", headers={"Authorization": "Bearer test-token"})
        assert response.status_code == 422  # Validation error for per_page > 500

        # Test that maximum valid page size works (500)
        response = client.get("/admin/tools?page=1&per_page=500", headers={"Authorization": "Bearer test-token"})
        assert response.status_code == 200
        data = response.json()
        assert data["pagination"]["per_page"] == 500

        # Test that invalid page number returns validation error (422)
        # FastAPI validates Query parameters at router level
        response = client.get("/admin/tools?page=0&per_page=10", headers={"Authorization": "Bearer test-token"})
        assert response.status_code == 422  # Validation error for page < 1

        # Test that valid minimum values work
        response = client.get("/admin/tools?page=1&per_page=1", headers={"Authorization": "Bearer test-token"})
        assert response.status_code == 200
        data = response.json()
        assert data["pagination"]["page"] == 1
        assert data["pagination"]["per_page"] == 1

        # Cleanup
        app.dependency_overrides.clear()
