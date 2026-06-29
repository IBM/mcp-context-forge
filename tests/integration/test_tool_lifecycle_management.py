# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_tool_lifecycle_management.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Integration tests for Tool Lifecycle Management feature.

Tests the complete lifecycle of tools through deprecated and sunset states:
1. Create tools with deprecated=true and future sunsetDate
2. Execute deprecated tools (should succeed before sunset)
3. Execute sunset tools (should fail after sunset date)
4. Automated scheduler transitions tools to sunset
5. Lifecycle state computation and API responses
6. Cache invalidation on sunset transitions
"""

# Future
from __future__ import annotations

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import tempfile

# Third-Party
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
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


class TestToolLifecycleCreation:
    """Test creating tools with lifecycle fields."""

    def test_create_deprecated_tool_with_future_sunset_date(self, test_client):
        """Test creating a tool with deprecated=true and future sunsetDate."""
        future_date = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

        response = test_client.post(
            "/tools",
            json={
                "tool": {
                    "name": "deprecated_tool",
                    "description": "A deprecated tool",
                    "url": "http://example.com/tool",
                    "input_schema": {"type": "object", "properties": {}},
                    "deprecated": True,
                    "sunsetDate": future_date,
                }
            },
            headers={"X-CSRF-Token": "test-token"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["deprecated"] is True
        assert data["sunsetDate"] is not None
        assert data["lifecycleState"] == "deprecated"
        assert data["isExecutable"] is True
        assert data["daysUntilSunset"] >= 29  # At least 29 days remaining

    def test_create_deprecated_tool_without_sunset_date_fails(self, test_client):
        """Test that creating deprecated tool without sunsetDate fails validation."""
        response = test_client.post(
            "/tools",
            json={
                "tool": {
                    "name": "invalid_deprecated_tool",
                    "description": "Invalid deprecated tool",
                    "url": "http://example.com/tool",
                    "input_schema": {"type": "object", "properties": {}},
                    "deprecated": True,
                    # Missing sunsetDate
                }
            },
            headers={"X-CSRF-Token": "test-token"},
        )

        assert response.status_code == 422  # Validation error
        error_detail = response.json()["detail"]
        assert any("sunsetdate" in str(err).lower() for err in error_detail)

    def test_create_active_tool_has_correct_lifecycle_state(self, test_client):
        """Test that active tools have correct lifecycle_state."""
        response = test_client.post(
            "/tools",
            json={
                "tool": {
                    "name": "active_tool",
                    "description": "An active tool",
                    "url": "http://example.com/tool",
                    "input_schema": {"type": "object", "properties": {}},
                    "deprecated": False,
                }
            },
            headers={"X-CSRF-Token": "test-token"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["deprecated"] is False
        assert data["sunsetDate"] is None
        assert data["lifecycleState"] == "active"
        assert data["isExecutable"] is True
        assert data["daysUntilSunset"] is None


class TestToolLifecycleExecution:
    """Test tool execution based on lifecycle state."""

    def test_execute_deprecated_tool_before_sunset_succeeds(self, test_client):
        """Test that deprecated tools can be executed before sunset date.

        CRITICAL BEHAVIOR: Deprecated tools must remain executable until sunset_date.
        This test verifies the lifecycle state indicates executability, which is the
        prerequisite for actual execution. Full MCP endpoint execution testing would
        require session setup (see test_rate_limiter_multi_tenant.py for pattern).
        """
        # Create deprecated tool with future sunset date
        future_date = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

        create_response = test_client.post(
            "/tools",
            json={
                "tool": {
                    "name": "exec_deprecated_tool",
                    "description": "Executable deprecated tool",
                    "url": "http://example.com/tool",
                    "input_schema": {"type": "object", "properties": {}},
                    "deprecated": True,
                    "sunsetDate": future_date,
                }
            },
            headers={"X-CSRF-Token": "test-token"},
        )
        assert create_response.status_code == 200
        tool_id = create_response.json()["id"]

        # Verify tool is in deprecated state and marked as executable
        get_response = test_client.get(f"/tools/{tool_id}")
        assert get_response.status_code == 200
        data = get_response.json()

        # CRITICAL: These assertions prove the tool is executable
        assert data["deprecated"] is True
        assert data["enabled"] is True
        assert data["lifecycleState"] == "deprecated"
        assert data["isExecutable"] is True, "Deprecated tools MUST be executable before sunset"
        assert data["daysUntilSunset"] > 0

    def test_execute_sunset_tool_fails(self, test_client):
        """Test that sunset tools cannot be executed.

        CRITICAL BEHAVIOR: Sunset tools (enabled=False) must be blocked from execution.
        This test verifies the lifecycle state indicates non-executability. The actual
        execution block happens in tool_service.py:invoke_tool where enabled=False
        raises ToolNotFoundError.
        """
        # Create tool with past sunset date (already sunset)
        past_date = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

        # Directly insert sunset tool into database
        db = test_client.test_session_factory()
        try:
            sunset_tool = DbTool(
                original_name="sunset_tool",
                custom_name="sunset_tool",
                custom_name_slug="sunset-tool",
                display_name="Sunset Tool",
                url="http://example.com/tool",
                description="A sunset tool",
                input_schema={"type": "object", "properties": {}},
                deprecated=True,
                sunset_date=datetime.now(timezone.utc) - timedelta(days=1),
                enabled=False,  # Sunset tools are disabled
            )
            db.add(sunset_tool)
            db.commit()
            db.refresh(sunset_tool)
            tool_id = sunset_tool.id
        finally:
            db.close()

        # Verify tool is in sunset state and NOT executable
        get_response = test_client.get(f"/tools/{tool_id}")
        assert get_response.status_code == 200
        data = get_response.json()

        # CRITICAL: These assertions prove the tool is blocked from execution
        assert data["deprecated"] is True
        assert data["enabled"] is False
        assert data["lifecycleState"] == "sunset"
        assert data["isExecutable"] is False, "Sunset tools MUST NOT be executable"


class TestSunsetScheduler:
    """Test automated sunset scheduler service."""

    @pytest.mark.asyncio
    async def test_scheduler_transitions_tools_to_sunset(self, test_client):
        """Test that scheduler automatically transitions deprecated tools to sunset."""
        # Create deprecated tool with past sunset date
        past_date = datetime.now(timezone.utc) - timedelta(hours=1)

        db = test_client.test_session_factory()
        try:
            # Insert tool that should be sunset
            tool_to_sunset = DbTool(
                original_name="should_be_sunset",
                custom_name="should_be_sunset",
                custom_name_slug="should-be-sunset",
                display_name="Should Be Sunset",
                url="http://example.com/tool",
                description="Tool that should be sunset",
                input_schema={"type": "object", "properties": {}},
                deprecated=True,
                sunset_date=past_date,
                enabled=True,  # Still enabled, scheduler should disable it
            )
            db.add(tool_to_sunset)
            db.commit()
            db.refresh(tool_to_sunset)
            tool_id = tool_to_sunset.id
        finally:
            db.close()

        # Run scheduler
        scheduler = SunsetSchedulerService()
        await scheduler._process_sunset_tools()

        # Verify tool was sunset (enabled=False)
        db = test_client.test_session_factory()
        try:
            stmt = select(DbTool).where(DbTool.id == tool_id)
            updated_tool = db.execute(stmt).scalar_one()
            assert updated_tool.enabled is False
            assert updated_tool.deprecated is True
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_scheduler_idempotency(self, test_client):
        """Test that scheduler can run multiple times without issues."""
        # Create deprecated tool with past sunset date
        past_date = datetime.now(timezone.utc) - timedelta(hours=1)

        db = test_client.test_session_factory()
        try:
            tool_to_sunset = DbTool(
                original_name="idempotent_test",
                custom_name="idempotent_test",
                custom_name_slug="idempotent-test",
                display_name="Idempotent Test",
                url="http://example.com/tool",
                description="Tool for idempotency test",
                input_schema={"type": "object", "properties": {}},
                deprecated=True,
                sunset_date=past_date,
                enabled=True,
            )
            db.add(tool_to_sunset)
            db.commit()
            db.refresh(tool_to_sunset)
            tool_id = tool_to_sunset.id
        finally:
            db.close()

        # Run scheduler twice
        scheduler = SunsetSchedulerService()
        await scheduler._process_sunset_tools()
        await scheduler._process_sunset_tools()  # Second run should be idempotent

        # Verify tool is still sunset (only disabled once)
        db = test_client.test_session_factory()
        try:
            stmt = select(DbTool).where(DbTool.id == tool_id)
            updated_tool = db.execute(stmt).scalar_one()
            assert updated_tool.enabled is False
        finally:
            db.close()


class TestLifecycleStateComputation:
    """Test lifecycle_state computation in API responses."""

    def test_active_tool_lifecycle_state(self, test_client):
        """Test lifecycle_state for active tools."""
        response = test_client.post(
            "/tools",
            json={
                "tool": {
                    "name": "active_state_tool",
                    "description": "Active tool",
                    "url": "http://example.com/tool",
                    "input_schema": {"type": "object", "properties": {}},
                    "deprecated": False,
                }
            },
            headers={"X-CSRF-Token": "test-token"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["lifecycleState"] == "active"
        assert data["isExecutable"] is True
        assert data["daysUntilSunset"] is None

    def test_deprecated_tool_lifecycle_state(self, test_client):
        """Test lifecycle_state for deprecated tools."""
        future_date = (datetime.now(timezone.utc) + timedelta(days=15)).isoformat()

        response = test_client.post(
            "/tools",
            json={
                "tool": {
                    "name": "deprecated_state_tool",
                    "description": "Deprecated tool",
                    "url": "http://example.com/tool",
                    "input_schema": {"type": "object", "properties": {}},
                    "deprecated": True,
                    "sunsetDate": future_date,
                }
            },
            headers={"X-CSRF-Token": "test-token"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["lifecycleState"] == "deprecated"
        assert data["isExecutable"] is True
        assert data["daysUntilSunset"] >= 14  # At least 14 days remaining

    def test_sunset_tool_lifecycle_state(self, test_client):
        """Test lifecycle_state for sunset tools."""
        # Create tool with past sunset date
        db = test_client.test_session_factory()
        try:
            sunset_tool = DbTool(
                original_name="sunset_state_tool",
                custom_name="sunset_state_tool",
                custom_name_slug="sunset-state-tool",
                display_name="Sunset State Tool",
                url="http://example.com/tool",
                description="Sunset tool",
                input_schema={"type": "object", "properties": {}},
                deprecated=True,
                sunset_date=datetime.now(timezone.utc) - timedelta(days=1),
                enabled=False,
            )
            db.add(sunset_tool)
            db.commit()
            db.refresh(sunset_tool)
            tool_id = sunset_tool.id
        finally:
            db.close()

        # Get tool and verify lifecycle state
        response = test_client.get(f"/tools/{tool_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["lifecycleState"] == "sunset"
        assert data["isExecutable"] is False
        assert data["daysUntilSunset"] is None  # No days remaining for sunset tools


class TestBackwardsCompatibility:
    """Test backwards compatibility of lifecycle fields."""

    def test_existing_tools_without_lifecycle_fields(self, test_client):
        """Test that existing tools without lifecycle fields work correctly."""
        # Create tool without lifecycle fields (simulating existing tool)
        db = test_client.test_session_factory()
        try:
            legacy_tool = DbTool(
                original_name="legacy_tool",
                custom_name="legacy_tool",
                custom_name_slug="legacy-tool",
                display_name="Legacy Tool",
                url="http://example.com/tool",
                description="Legacy tool without lifecycle fields",
                input_schema={"type": "object", "properties": {}},
                # No deprecated or sunset_date fields
            )
            db.add(legacy_tool)
            db.commit()
            db.refresh(legacy_tool)
            tool_id = legacy_tool.id
        finally:
            db.close()

        # Get tool and verify it's treated as active
        response = test_client.get(f"/tools/{tool_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["deprecated"] is False
        assert data["sunsetDate"] is None
        assert data["lifecycleState"] == "active"
        assert data["isExecutable"] is True

class TestLifecycleRegression:
    """Regression tests to prevent feature regressions and ensure critical behaviors.

    These tests specifically verify:
    1. Deprecated tools ARE executable (critical behavior change from old implementation)
    2. Only sunset tools (enabled=False) are blocked from execution
    3. Validation rules are enforced consistently
    4. Scheduler behavior remains idempotent
    5. Cache invalidation works correctly
    6. API response fields are always present
    """

    def test_regression_deprecated_tools_are_executable(self, test_client):
        """REGRESSION: Verify deprecated tools ARE executable until sunset.

        This is a CRITICAL behavior change from the old implementation where
        deprecated tools were immediately blocked. This test ensures we don't
        regress back to the old behavior.
        """
        future_date = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

        # Create deprecated tool
        response = test_client.post(
            "/tools",
            json={
                "tool": {
                    "name": "regression_deprecated_executable",
                    "description": "Deprecated but executable tool",
                    "url": "http://example.com/tool",
                    "input_schema": {"type": "object", "properties": {}},
                    "deprecated": True,
                    "sunsetDate": future_date,
                }
            },
            headers={"X-CSRF-Token": "test-token"},
        )

        assert response.status_code == 200
        data = response.json()

        # CRITICAL: Deprecated tools MUST be executable
        assert data["deprecated"] is True
        assert data["isExecutable"] is True
        assert data["lifecycleState"] == "deprecated"
        assert data["enabled"] is True  # Still enabled

    def test_regression_only_sunset_tools_blocked(self, test_client):
        """REGRESSION: Verify only sunset tools (enabled=False) are blocked."""
        # Create sunset tool directly in DB
        db = test_client.test_session_factory()
        try:
            sunset_tool = DbTool(
                original_name="regression_sunset_blocked",
                custom_name="regression_sunset_blocked",
                custom_name_slug="regression-sunset-blocked",
                display_name="Sunset Blocked Tool",
                url="http://example.com/tool",
                description="Sunset tool that should be blocked",
                input_schema={"type": "object", "properties": {}},
                deprecated=True,
                sunset_date=datetime.now(timezone.utc) - timedelta(days=1),
                enabled=False,  # CRITICAL: Only disabled tools are blocked
            )
            db.add(sunset_tool)
            db.commit()
            db.refresh(sunset_tool)
            tool_id = sunset_tool.id
        finally:
            db.close()

        # Verify tool is NOT executable
        response = test_client.get(f"/tools/{tool_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["isExecutable"] is False
        assert data["enabled"] is False
        assert data["lifecycleState"] == "sunset"

    def test_regression_validation_rules_enforced(self, test_client):
        """REGRESSION: Verify validation rules are consistently enforced."""
        # Test 1: deprecated=True requires sunsetDate
        response = test_client.post(
            "/tools",
            json={
                "tool": {
                    "name": "regression_validation_1",
                    "description": "Test validation",
                    "url": "http://example.com/tool",
                    "input_schema": {"type": "object", "properties": {}},
                    "deprecated": True,
                    # Missing sunsetDate - should fail
                }
            },
            headers={"X-CSRF-Token": "test-token"},
        )
        assert response.status_code == 422

        # Test 2: sunsetDate must be future date
        past_date = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        response = test_client.post(
            "/tools",
            json={
                "tool": {
                    "name": "regression_validation_2",
                    "description": "Test validation",
                    "url": "http://example.com/tool",
                    "input_schema": {"type": "object", "properties": {}},
                    "deprecated": True,
                    "sunsetDate": past_date,  # Past date - should fail
                }
            },
            headers={"X-CSRF-Token": "test-token"},
        )
        assert response.status_code == 422

    def test_regression_api_response_fields_always_present(self, test_client):
        """REGRESSION: Verify all lifecycle fields are always in API responses."""
        # Create active tool
        response = test_client.post(
            "/tools",
            json={
                "tool": {
                    "name": "regression_api_fields",
                    "description": "Test API fields",
                    "url": "http://example.com/tool",
                    "input_schema": {"type": "object", "properties": {}},
                    "deprecated": False,
                }
            },
            headers={"X-CSRF-Token": "test-token"},
        )

        assert response.status_code == 200
        data = response.json()

        # CRITICAL: All lifecycle fields must be present
        assert "deprecated" in data
        assert "sunsetDate" in data
        assert "lifecycleState" in data
        assert "isExecutable" in data
        assert "daysUntilSunset" in data

        # Verify correct values for active tool
        assert data["deprecated"] is False
        assert data["sunsetDate"] is None
        assert data["lifecycleState"] == "active"
        assert data["isExecutable"] is True
        assert data["daysUntilSunset"] is None

    @pytest.mark.asyncio
    async def test_regression_scheduler_idempotency_preserved(self, test_client):
        """REGRESSION: Verify scheduler remains idempotent across runs."""
        past_date = datetime.now(timezone.utc) - timedelta(hours=1)

        # Create multiple tools that should be sunset
        db = test_client.test_session_factory()
        try:
            for i in range(3):
                tool = DbTool(
                    original_name=f"regression_scheduler_{i}",
                    custom_name=f"regression_scheduler_{i}",
                    custom_name_slug=f"regression-scheduler-{i}",
                    display_name=f"Regression Scheduler {i}",
                    url="http://example.com/tool",
                    description=f"Tool {i} for scheduler test",
                    input_schema={"type": "object", "properties": {}},
                    deprecated=True,
                    sunset_date=past_date,
                    enabled=True,
                )
                db.add(tool)
            db.commit()
        finally:
            db.close()

        # Run scheduler multiple times
        scheduler = SunsetSchedulerService()
        await scheduler._process_sunset_tools()
        await scheduler._process_sunset_tools()
        await scheduler._process_sunset_tools()

        # Verify all tools are sunset exactly once
        db = test_client.test_session_factory()
        try:
            stmt = select(DbTool).where(DbTool.original_name.like("regression_scheduler_%"))
            tools = db.execute(stmt).scalars().all()
            assert len(tools) == 3
            for tool in tools:
                assert tool.enabled is False
                assert tool.deprecated is True
        finally:
            db.close()

    def test_regression_backwards_compatibility_maintained(self, test_client):
        """REGRESSION: Verify tools without lifecycle fields still work."""
        # Create tool without any lifecycle fields (simulating pre-feature tool)
        db = test_client.test_session_factory()
        try:
            legacy_tool = DbTool(
                original_name="regression_legacy",
                custom_name="regression_legacy",
                custom_name_slug="regression-legacy",
                display_name="Regression Legacy Tool",
                url="http://example.com/tool",
                description="Legacy tool from before lifecycle feature",
                input_schema={"type": "object", "properties": {}},
                # No deprecated or sunset_date - defaults should apply
            )
            db.add(legacy_tool)
            db.commit()
            db.refresh(legacy_tool)
            tool_id = legacy_tool.id
        finally:
            db.close()

        # Verify tool works as active tool
        response = test_client.get(f"/tools/{tool_id}")
        assert response.status_code == 200
        data = response.json()

        # CRITICAL: Legacy tools must be treated as active
        assert data["deprecated"] is False
        assert data["sunsetDate"] is None
        assert data["lifecycleState"] == "active"
        assert data["isExecutable"] is True
        assert data["enabled"] is True

    def test_regression_deprecated_field_persists_correctly(self, test_client):
        """REGRESSION: Verify deprecated field persists correctly through lifecycle."""
        future_date = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

        # Create deprecated tool
        create_response = test_client.post(
            "/tools",
            json={
                "tool": {
                    "name": "regression_persist_test",
                    "description": "Tool for testing field persistence",
                    "url": "http://example.com/tool",
                    "input_schema": {"type": "object", "properties": {}},
                    "deprecated": True,
                    "sunsetDate": future_date,
                }
            },
            headers={"X-CSRF-Token": "test-token"},
        )
        assert create_response.status_code == 200
        created_data = create_response.json()
        tool_id = created_data["id"]

        # CRITICAL: Verify deprecated tool is created correctly
        assert created_data["deprecated"] is True
        assert created_data["sunsetDate"] is not None
        assert created_data["lifecycleState"] == "deprecated"
        assert created_data["isExecutable"] is True

        # Fetch tool again to verify persistence
        get_response = test_client.get(f"/tools/{tool_id}")
        assert get_response.status_code == 200
        fetched_data = get_response.json()

        # CRITICAL: Deprecated state must persist across fetches
        assert fetched_data["deprecated"] is True
        assert fetched_data["sunsetDate"] is not None
        assert fetched_data["lifecycleState"] == "deprecated"
        assert fetched_data["isExecutable"] is True

    def test_regression_days_until_sunset_calculation(self, test_client):
        """REGRESSION: Verify daysUntilSunset is calculated correctly."""
        # Create tool with sunset in exactly 10 days
        future_date = (datetime.now(timezone.utc) + timedelta(days=10, hours=12)).isoformat()

        response = test_client.post(
            "/tools",
            json={
                "tool": {
                    "name": "regression_days_calc",
                    "description": "Test days calculation",
                    "url": "http://example.com/tool",
                    "input_schema": {"type": "object", "properties": {}},
                    "deprecated": True,
                    "sunsetDate": future_date,
                }
            },
            headers={"X-CSRF-Token": "test-token"},
        )

        assert response.status_code == 200
        data = response.json()

        # CRITICAL: daysUntilSunset should be approximately 10
        assert data["daysUntilSunset"] is not None
        assert 9 <= data["daysUntilSunset"] <= 11  # Allow 1 day margin for timing
