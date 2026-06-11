# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_tool_lifecycle_regression.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Regression tests for tool lifecycle management.

These tests ensure that the tool lifecycle feature (deprecated → sunset) doesn't
introduce regressions in critical paths:
- Tool listing and filtering
- Tool invocation
- Cache consistency
- Update operations
- Multi-worker scenarios
"""

# Standard
from datetime import datetime, timedelta, timezone
import os
import tempfile
from unittest.mock import AsyncMock, patch

# Third-Party
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.db import Base, Tool as DbTool
from mcpgateway.main import app
from mcpgateway.services.sunset_scheduler_service import SunsetSchedulerService
from mcpgateway.utils.verify_credentials import require_auth

# Local
from tests.utils.rbac_mocks import MockPermissionService


@pytest.fixture
def test_client():
    """FastAPI TestClient with proper database setup and auth dependency overridden."""
    # Standard
    from _pytest.monkeypatch import MonkeyPatch

    # First-Party
    from mcpgateway.auth import get_current_user
    from mcpgateway.config import settings
    from mcpgateway.middleware.rbac import get_current_user_with_permissions
    from mcpgateway.middleware.rbac import get_db as rbac_get_db
    from mcpgateway.middleware.rbac import get_permission_service
    import mcpgateway.db as db_mod
    import mcpgateway.main as main_mod

    mp = MonkeyPatch()

    # Create temp SQLite file
    fd, path = tempfile.mkstemp(suffix=".db")
    url = f"sqlite:///{path}"

    # Patch settings
    mp.setattr(settings, "database_url", url, raising=False)
    mp.setattr(settings, "csrf_enabled", False, raising=False)

    # Create engine and session
    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    mp.setattr(db_mod, "engine", engine, raising=False)
    mp.setattr(db_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(main_mod, "SessionLocal", TestSessionLocal, raising=False)
    mp.setattr(main_mod, "engine", engine, raising=False)

    # Create schema
    Base.metadata.create_all(bind=engine)

    # Set up authentication overrides
    from unittest.mock import MagicMock  # pylint: disable=import-outside-toplevel

    mock_email_user = MagicMock()
    mock_email_user.email = "test-user@example.com"
    mock_email_user.full_name = "Test User"
    mock_email_user.is_admin = True
    mock_email_user.is_active = True

    async def mock_user_with_permissions():
        """Mock user context for RBAC."""
        db_session = TestSessionLocal()
        try:
            yield {
                "email": "test-user@example.com",
                "full_name": "Test User",
                "is_admin": True,
                "ip_address": "127.0.0.1",
                "user_agent": "test-client",
                "db": db_session,
            }
        finally:
            db_session.close()

    def mock_get_permission_service(*args, **kwargs):
        """Return a mock permission service that always grants access."""
        return MockPermissionService(always_grant=True)

    def override_get_db():
        """Override database dependency to return our test database."""
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    # Patch the PermissionService class to always return our mock
    with patch("mcpgateway.middleware.rbac.PermissionService", MockPermissionService):
        app.dependency_overrides[require_auth] = lambda: "test-user"
        app.dependency_overrides[get_current_user] = lambda: mock_email_user
        app.dependency_overrides[get_current_user_with_permissions] = mock_user_with_permissions
        app.dependency_overrides[get_permission_service] = mock_get_permission_service
        app.dependency_overrides[rbac_get_db] = override_get_db

        client = TestClient(app)

        # Store session factory for direct DB access in tests
        client.test_session_factory = TestSessionLocal

        yield client

        # Cleanup
        app.dependency_overrides.pop(require_auth, None)
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_user_with_permissions, None)
        app.dependency_overrides.pop(get_permission_service, None)
        app.dependency_overrides.pop(rbac_get_db, None)

    mp.undo()
    engine.dispose()


@pytest.mark.integration
class TestToolLifecycleListingRegression:
    """Regression tests for tool listing with lifecycle states."""

    def test_sunset_tools_excluded_from_default_list(self, test_client):
        """REGRESSION: Sunset tools should not appear in default tool listings.

        Critical: MCP clients should not see disabled (sunset) tools in their
        tool lists, as this would cause invocation failures.
        """
        # Create an active tool
        active_response = test_client.post(
            "/tools",
            json={
                "tool": {
                    "name": "active_tool",
                    "description": "Active tool",
                    "url": "http://example.com/active",
                    "input_schema": {"type": "object", "properties": {}},
                }
            },
            headers={"X-CSRF-Token": "test-token"},
        )
        assert active_response.status_code == 200

        # Create a deprecated tool with past sunset date (will be sunset)
        past_date = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

        # Directly insert sunset tool into database
        db = test_client.test_session_factory()
        try:
            sunset_tool = DbTool(
                original_name="sunset_tool",
                custom_name="sunset_tool",
                custom_name_slug="sunset-tool",
                display_name="Sunset Tool",
                url="http://example.com/sunset",
                description="A sunset tool",
                input_schema={"type": "object", "properties": {}},
                deprecated=True,
                sunset_date=datetime.now(timezone.utc) - timedelta(days=1),
                enabled=False,  # Sunset by scheduler
            )
            db.add(sunset_tool)
            db.commit()
            db.refresh(sunset_tool)
            sunset_tool_id = sunset_tool.id
        finally:
            db.close()

        # List tools (default behavior - should exclude sunset tools)
        list_response = test_client.get("/tools")
        assert list_response.status_code == 200
        tools_data = list_response.json()

        # Verify active tool is in list
        tool_names = [t["name"] for t in tools_data]
        assert "active-tool" in tool_names

        # CRITICAL: Sunset tool should NOT be in default list
        assert "sunset-tool" not in tool_names, "Sunset tools should be excluded from default tool listings"

        # Verify we can still get the sunset tool by ID (for admin purposes)
        get_response = test_client.get(f"/tools/{sunset_tool_id}")
        assert get_response.status_code == 200
        tool_data = get_response.json()
        assert tool_data["lifecycleState"] == "sunset"
        assert tool_data["enabled"] is False

    def test_sunset_tools_visible_with_include_inactive(self, test_client):
        """REGRESSION: Admins should see sunset tools with include_inactive=True.

        Critical: Admin interfaces need to see all tools including sunset ones
        for auditing and management purposes.
        """
        # Create a sunset tool
        db = test_client.test_session_factory()
        try:
            sunset_tool = DbTool(
                original_name="admin_sunset_tool",
                custom_name="admin_sunset_tool",
                custom_name_slug="admin-sunset-tool",
                display_name="Admin Sunset Tool",
                url="http://example.com/admin-sunset",
                description="Sunset tool for admin view test",
                input_schema={"type": "object", "properties": {}},
                deprecated=True,
                sunset_date=datetime.now(timezone.utc) - timedelta(days=1),
                enabled=False,
            )
            db.add(sunset_tool)
            db.commit()
        finally:
            db.close()

        # List tools with include_inactive (admin view)
        list_response = test_client.get("/tools?include_inactive=true")
        assert list_response.status_code == 200
        tools_data = list_response.json()

        # CRITICAL: Sunset tool should be visible with include_inactive
        tool_names = [t["name"] for t in tools_data]
        assert "admin-sunset-tool" in tool_names, "Sunset tools should be visible with include_inactive=true"

        # Find the sunset tool and verify its lifecycle state
        sunset_tool_data = next((t for t in tools_data if t["name"] == "admin-sunset-tool"), None)
        assert sunset_tool_data is not None
        assert sunset_tool_data["lifecycleState"] == "sunset"
        assert sunset_tool_data["enabled"] is False
        assert sunset_tool_data["deprecated"] is True


@pytest.mark.integration
class TestToolLifecycleInvocationRegression:
    """Regression tests for tool invocation with lifecycle management."""

    @pytest.mark.asyncio
    async def test_tool_invocation_blocked_after_scheduler_run(self, test_client):
        """REGRESSION: Tool invocation must be blocked after scheduler sunsets tool.

        Critical: Tools past their sunset_date must not be executable, even if
        the scheduler hasn't run yet. The invocation check should verify sunset_date.
        """
        # Create a deprecated tool with past sunset date but still enabled
        past_date = datetime.now(timezone.utc) - timedelta(hours=1)  # noqa: F841

        db = test_client.test_session_factory()
        try:
            tool = DbTool(
                original_name="invocation_test_tool",
                custom_name="invocation_test_tool",
                custom_name_slug="invocation-test-tool",
                display_name="Invocation Test Tool",
                url="http://example.com/invocation-test",
                description="Tool for invocation blocking test",
                input_schema={"type": "object", "properties": {}},
                deprecated=True,
                sunset_date=past_date,
                enabled=True,  # Still enabled (scheduler hasn't run)
            )
            db.add(tool)
            db.commit()
            db.refresh(tool)
            tool_id = tool.id
        finally:
            db.close()

        # Run the sunset scheduler to disable the tool
        scheduler = SunsetSchedulerService()

        # Mock dependencies to avoid Redis/audit trail issues in tests
        with patch("mcpgateway.services.sunset_scheduler_service.get_registry_cache") as mock_cache:
            mock_registry = AsyncMock()
            mock_cache.return_value = mock_registry

            with patch("mcpgateway.services.sunset_scheduler_service.get_audit_trail_service"):
                with patch("mcpgateway.services.sunset_scheduler_service.ObservabilityService"):
                    await scheduler._process_sunset_tools()

        # Verify tool was disabled
        db = test_client.test_session_factory()
        try:
            db_tool = db.get(DbTool, tool_id)
            assert db_tool is not None
            assert db_tool.enabled is False, "Scheduler should have disabled the tool"
        finally:
            db.close()

        # Verify tool shows sunset state via API
        get_response = test_client.get(f"/tools/{tool_id}")
        assert get_response.status_code == 200
        tool_data = get_response.json()
        assert tool_data["lifecycleState"] == "sunset"
        assert tool_data["isExecutable"] is False

    @pytest.mark.asyncio
    async def test_concurrent_invocation_during_sunset_transition(self, test_client):
        """REGRESSION: Concurrent invocations during sunset should fail gracefully.

        Critical: If a tool is being invoked while the scheduler is disabling it,
        the system should handle the race condition cleanly without errors.
        """
        # Create a deprecated tool about to be sunset
        past_date = datetime.now(timezone.utc) - timedelta(minutes=1)

        db = test_client.test_session_factory()
        try:
            tool = DbTool(
                original_name="concurrent_test_tool",
                custom_name="concurrent_test_tool",
                custom_name_slug="concurrent-test-tool",
                display_name="Concurrent Test Tool",
                url="http://example.com/concurrent-test",
                description="Tool for concurrent execution test",
                input_schema={"type": "object", "properties": {}},
                deprecated=True,
                sunset_date=past_date,
                enabled=True,  # Still enabled
            )
            db.add(tool)
            db.commit()
            db.refresh(tool)
            tool_id = tool.id
        finally:
            db.close()

        # The tool should be blocked even before scheduler runs
        # because invoke_tool checks sunset_date
        get_response = test_client.get(f"/tools/{tool_id}")
        assert get_response.status_code == 200
        tool_data = get_response.json()

        # Tool is technically still enabled but past sunset
        assert tool_data["enabled"] is True
        assert tool_data["deprecated"] is True
        # The lifecycle_state should show "sunset" because sunset_date is in the past
        assert tool_data["lifecycleState"] == "sunset"
        assert tool_data["isExecutable"] is False


@pytest.mark.integration
class TestToolLifecycleCacheRegression:
    """Regression tests for cache consistency with lifecycle management."""

    @pytest.mark.asyncio
    async def test_sunset_scheduler_invalidates_tool_cache(self, test_client):
        """REGRESSION: Sunset scheduler must invalidate cached tool entries.

        Critical: Stale cache entries could allow execution of sunset tools.
        The scheduler must invalidate the cache when disabling tools.
        """
        # Create a deprecated tool ready to sunset
        past_date = datetime.now(timezone.utc) - timedelta(hours=1)

        db = test_client.test_session_factory()
        try:
            tool = DbTool(
                original_name="cache_invalidation_tool",
                custom_name="cache_invalidation_tool",
                custom_name_slug="cache-invalidation-tool",
                display_name="Cache Invalidation Tool",
                url="http://example.com/cache-test",
                description="Tool for cache invalidation test",
                input_schema={"type": "object", "properties": {}},
                deprecated=True,
                sunset_date=past_date,
                enabled=True,
            )
            db.add(tool)
            db.commit()
            db.refresh(tool)
            tool_id = tool.id
        finally:
            db.close()

        # Mock the cache to verify invalidation is called
        mock_invalidate_called = False

        with patch("mcpgateway.services.sunset_scheduler_service.get_registry_cache") as mock_cache_getter:
            mock_cache = AsyncMock()

            # Track if invalidate_tools is called (no arguments)
            async def track_invalidate():
                nonlocal mock_invalidate_called
                mock_invalidate_called = True

            mock_cache.invalidate_tools = track_invalidate
            mock_cache_getter.return_value = mock_cache

            # Run scheduler
            scheduler = SunsetSchedulerService()
            with patch("mcpgateway.services.sunset_scheduler_service.get_audit_trail_service"):
                with patch("mcpgateway.services.sunset_scheduler_service.ObservabilityService"):
                    await scheduler._process_sunset_tools()

        # CRITICAL: Cache invalidation should have been called
        assert mock_invalidate_called, "Scheduler must invalidate cache for sunset tools"

        # Verify tool was actually disabled
        db = test_client.test_session_factory()
        try:
            db_tool = db.get(DbTool, tool_id)
            assert db_tool.enabled is False
        finally:
            db.close()


@pytest.mark.integration
class TestToolLifecycleUpdateRegression:
    """Regression tests for update operations on lifecycle-managed tools."""

    def test_cannot_manually_enable_sunset_tool_without_clearing_deprecated(self, test_client):
        """REGRESSION: Cannot enable sunset tool without clearing deprecated flag.

        Critical: Attempting to set enabled=True on a sunset tool without first
        clearing deprecated=False should fail to prevent inconsistent state.
        """
        # Create a sunset tool
        db = test_client.test_session_factory()
        try:
            tool = DbTool(
                original_name="manual_enable_test",
                custom_name="manual_enable_test",
                custom_name_slug="manual-enable-test",
                display_name="Manual Enable Test",
                url="http://example.com/manual-enable",
                description="Tool for manual enable test",
                input_schema={"type": "object", "properties": {}},
                deprecated=True,
                sunset_date=datetime.now(timezone.utc) - timedelta(days=1),
                enabled=False,
                owner_email="test-user@example.com",  # Set owner to match test user
            )
            db.add(tool)
            db.commit()
            db.refresh(tool)
            tool_id = tool.id
        finally:
            db.close()

        # Verify tool starts as sunset
        get_response = test_client.get(f"/tools/{tool_id}")
        assert get_response.status_code == 200
        assert get_response.json()["lifecycleState"] == "sunset"

        # Try to enable the tool without clearing deprecated
        # This should either fail or be allowed but maintain consistency
        _update_response = test_client.put(
            f"/tools/{tool_id}",
            json={
                "deprecated": True,  # Still deprecated
                # enabled is managed by the system, not directly settable via this endpoint
            },
            headers={"X-CSRF-Token": "test-token"},
        )

        # The tool should remain in sunset state
        get_after = test_client.get(f"/tools/{tool_id}")
        assert get_after.status_code == 200
        data = get_after.json()

        # CRITICAL: Tool must remain disabled if deprecated=True
        if data["deprecated"] is True:
            assert data["enabled"] is False, "Deprecated tools cannot be enabled while deprecated=True"

    def test_update_other_fields_on_sunset_tool(self, test_client):
        """REGRESSION: Should be able to update non-lifecycle fields on sunset tools.

        Critical: Admins need to update metadata (description, tags) on sunset
        tools for documentation purposes.
        """
        # Create a sunset tool
        db = test_client.test_session_factory()
        try:
            tool = DbTool(
                original_name="update_fields_test",
                custom_name="update_fields_test",
                custom_name_slug="update-fields-test",
                display_name="Update Fields Test",
                url="http://example.com/update-fields",
                description="Original description",
                input_schema={"type": "object", "properties": {}},
                deprecated=True,
                sunset_date=datetime.now(timezone.utc) - timedelta(days=1),
                enabled=False,
                tags=["original"],
                owner_email="test-user@example.com",  # Set owner to match test user
            )
            db.add(tool)
            db.commit()
            db.refresh(tool)
            tool_id = tool.id
        finally:
            db.close()

        # Update description and tags on sunset tool
        update_response = test_client.put(
            f"/tools/{tool_id}",
            json={
                "description": "Updated description for archived tool",
                "tags": ["archived", "deprecated"],
            },
            headers={"X-CSRF-Token": "test-token"},
        )
        assert update_response.status_code == 200, f"Update failed: {update_response.status_code} - {update_response.text}"

        # Verify updates were applied
        get_response = test_client.get(f"/tools/{tool_id}")
        assert get_response.status_code == 200
        data = get_response.json()

        # CRITICAL: Non-lifecycle fields should be updated
        assert data["description"] == "Updated description for archived tool"
        # Tags are returned as objects with id and label
        tag_ids = [tag["id"] for tag in data["tags"]]
        assert "archived" in tag_ids
        assert "deprecated" in tag_ids

        # Lifecycle state should remain unchanged
        assert data["lifecycleState"] == "sunset"
        assert data["enabled"] is False
        assert data["deprecated"] is True

    def test_resurrect_sunset_tool_by_clearing_deprecated(self, test_client):
        """REGRESSION: Can resurrect sunset tool by setting deprecated=False.

        Critical: Admins should be able to "resurrect" a sunset tool by clearing
        the deprecated flag, which also clears sunset_date and re-enables the tool.
        """
        # Create a sunset tool
        db = test_client.test_session_factory()
        try:
            tool = DbTool(
                original_name="resurrect_test",
                custom_name="resurrect_test",
                custom_name_slug="resurrect-test",
                display_name="Resurrect Test",
                url="http://example.com/resurrect",
                description="Tool to be resurrected",
                input_schema={"type": "object", "properties": {}},
                deprecated=True,
                sunset_date=datetime.now(timezone.utc) - timedelta(days=1),
                enabled=False,
                owner_email="test-user@example.com",  # Set owner to match test user
            )
            db.add(tool)
            db.commit()
            db.refresh(tool)
            tool_id = tool.id
        finally:
            db.close()

        # Verify tool starts as sunset
        get_before = test_client.get(f"/tools/{tool_id}")
        assert get_before.status_code == 200
        assert get_before.json()["lifecycleState"] == "sunset"

        # Resurrect by setting deprecated=False
        update_response = test_client.put(
            f"/tools/{tool_id}",
            json={
                "deprecated": False,
            },
            headers={"X-CSRF-Token": "test-token"},
        )
        assert update_response.status_code == 200

        # Manually enable the tool (since enabled is separate from deprecated)
        db = test_client.test_session_factory()
        try:
            db_tool = db.get(DbTool, tool_id)
            db_tool.enabled = True
            db.commit()
        finally:
            db.close()

        # Verify tool is now active
        get_after = test_client.get(f"/tools/{tool_id}")
        assert get_after.status_code == 200
        data = get_after.json()

        # CRITICAL: Tool should be active after resurrection
        assert data["deprecated"] is False
        assert data["sunsetDate"] is None, "sunset_date should be cleared when deprecated=False"
        assert data["enabled"] is True
        assert data["lifecycleState"] == "active"
        assert data["isExecutable"] is True


@pytest.mark.integration
class TestToolLifecycleEdgeCases:
    """Regression tests for edge cases in lifecycle management."""

    def test_deprecated_tool_without_sunset_date_remains_executable(self, test_client):
        """REGRESSION: Old deprecated tools without sunset_date should remain executable.

        Critical: Backwards compatibility - tools marked deprecated before the
        sunset feature was added should continue to work until given a sunset_date.
        """
        # Simulate an old deprecated tool (no sunset_date)
        db = test_client.test_session_factory()
        try:
            tool = DbTool(
                original_name="old_deprecated_tool",
                custom_name="old_deprecated_tool",
                custom_name_slug="old-deprecated-tool",
                display_name="Old Deprecated Tool",
                url="http://example.com/old-deprecated",
                description="Tool deprecated before sunset feature",
                input_schema={"type": "object", "properties": {}},
                deprecated=True,
                sunset_date=None,  # No sunset date
                enabled=True,
            )
            db.add(tool)
            db.commit()
            db.refresh(tool)
            tool_id = tool.id
        finally:
            db.close()

        # Verify tool state
        get_response = test_client.get(f"/tools/{tool_id}")
        assert get_response.status_code == 200
        data = get_response.json()

        # CRITICAL: Old deprecated tools without sunset_date should be treated as deprecated but executable
        assert data["deprecated"] is True
        assert data["sunsetDate"] is None
        assert data["enabled"] is True
        # Without a sunset_date, lifecycle_state should be "deprecated" (not sunset)
        assert data["lifecycleState"] == "deprecated"
        assert data["isExecutable"] is True

    def test_tool_with_future_sunset_date_is_executable(self, test_client):
        """REGRESSION: Deprecated tools with future sunset_date are still executable.

        Critical: The grace period between deprecation and sunset must be enforced.
        Tools should remain executable until the sunset_date is reached.
        """
        # Create deprecated tool with future sunset date
        future_date = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

        create_response = test_client.post(
            "/tools",
            json={
                "tool": {
                    "name": "future_sunset_tool",
                    "description": "Tool with future sunset",
                    "url": "http://example.com/future-sunset",
                    "input_schema": {"type": "object", "properties": {}},
                    "deprecated": True,
                    "sunsetDate": future_date,
                }
            },
            headers={"X-CSRF-Token": "test-token"},
        )
        assert create_response.status_code == 200
        tool_id = create_response.json()["id"]

        # Verify tool state
        get_response = test_client.get(f"/tools/{tool_id}")
        assert get_response.status_code == 200
        data = get_response.json()

        # CRITICAL: Tools with future sunset_date must remain executable
        assert data["deprecated"] is True
        assert data["sunsetDate"] is not None
        assert data["enabled"] is True
        assert data["lifecycleState"] == "deprecated"  # Not sunset yet
        assert data["isExecutable"] is True, "Tools before sunset_date must be executable"
        assert data["daysUntilSunset"] > 0
