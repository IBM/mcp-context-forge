# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_audit_trail_transaction_isolation.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Integration tests for audit trail transaction isolation.

Tests verify that audit trail uses separate database sessions and that
main resource operations commit successfully even when audit logging fails.
This validates the separate session pattern documented in AGENTS.md.
"""

# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import AuditTrail, Base, Resource, Tool
from mcpgateway.schemas import ResourceCreate, ToolCreate
from mcpgateway.services.audit_trail_service import AuditTrailService
from mcpgateway.services.resource_service import ResourceService
from mcpgateway.services.tool_service import ToolService


@pytest.fixture
def test_db_engine():
    """Create test database engine with thread-safe SQLite."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def test_db_session(test_db_engine):
    """Create test database session."""
    TestSessionLocal = sessionmaker(bind=test_db_engine)
    session = TestSessionLocal()
    yield session
    session.close()


@pytest.fixture
def audit_service():
    """Create audit trail service instance."""
    return AuditTrailService()


@pytest.fixture(autouse=True)
def enable_audit_trail(monkeypatch):
    """Enable audit trail for all tests in this module."""
    monkeypatch.setattr(settings, "audit_trail_enabled", True)


@pytest.fixture(autouse=True)
def patch_session_local(test_db_engine, monkeypatch):
    """Patch SessionLocal to use test database.

    Patches both mcpgateway.db.SessionLocal (used by most code) and the
    module-local reference in audit_trail_service (imported at module
    level via ``from mcpgateway.db import SessionLocal``) so that audit
    writes land in the same in-memory SQLite instance as the main writes.
    """
    TestSessionLocal = sessionmaker(bind=test_db_engine)
    monkeypatch.setattr("mcpgateway.db.SessionLocal", TestSessionLocal)
    monkeypatch.setattr("mcpgateway.services.audit_trail_service.SessionLocal", TestSessionLocal)


class TestAuditTrailSeparateSession:
    """Tests for audit trail separate session pattern."""

    def test_audit_trail_separate_session_pattern(self, test_db_session, audit_service):
        """Verify audit trail uses separate session from main transaction.

        This test validates that:
        1. Main resource uses request-scoped session
        2. Audit logging creates its own independent session
        3. Both transactions complete successfully
        4. Both records persist in the database
        """
        # Create a tool directly in the main session
        tool = Tool(
            id="tool-123",
            original_name="test-tool",
            name="test-tool",
            description="Test tool for audit isolation",
            input_schema={"type": "object"},
            gateway_id="gw-1",
            team_id="public",
        )
        test_db_session.add(tool)
        test_db_session.commit()

        # Call audit service directly (it should create its own session)
        audit_entry = audit_service.log_action(
            action="CREATE",
            resource_type="tool",
            resource_id=tool.id,
            user_id="test-user@example.com",
            resource_name=tool.name,
            db=None,  # Force separate session creation
        )

        # Verify audit entry was created
        assert audit_entry is not None

        # Verify tool exists in database (using fresh query)
        tool_query = select(Tool).where(Tool.id == tool.id)
        tool_result = test_db_session.execute(tool_query).scalar_one_or_none()
        assert tool_result is not None
        assert tool_result.name == "test-tool"

        # Verify audit entry exists in database (using fresh query)
        audit_query = select(AuditTrail).where(
            AuditTrail.resource_type == "tool",
            AuditTrail.resource_id == tool.id,
            AuditTrail.action == "CREATE",
        )
        audit_result = test_db_session.execute(audit_query).scalar_one_or_none()
        assert audit_result is not None
        assert audit_result.user_id == "test-user@example.com"
        assert audit_result.success is True

    def test_audit_failure_does_not_rollback_main_resource(self, test_db_session, audit_service):
        """Verify main resource commits even if audit logging fails.

        This test validates the best-effort audit pattern:
        1. Main resource creation succeeds
        2. Audit logging fails (simulated)
        3. Main resource still persists in database
        4. No audit entry is created (audit failed gracefully)
        """
        # Create a tool directly in the main session
        tool = Tool(
            id="tool-456",
            original_name="test-tool-resilient",
            name="test-tool-resilient",
            description="Test tool for audit failure resilience",
            input_schema={"type": "object"},
            gateway_id="gw-1",
            team_id="public",
        )
        test_db_session.add(tool)
        test_db_session.commit()

        # Mock SessionLocal to raise exception when audit tries to create session
        with patch("mcpgateway.services.audit_trail_service.SessionLocal") as mock_session_local:
            mock_session_local.side_effect = RuntimeError("Simulated session creation failure")

            # Call audit service - should fail gracefully
            audit_entry = audit_service.log_action(
                action="CREATE",
                resource_type="tool",
                resource_id=tool.id,
                user_id="test-user@example.com",
                db=None,
            )

            # Audit should return None on failure
            assert audit_entry is None

        # Verify tool still exists in database
        tool_query = select(Tool).where(Tool.id == tool.id)
        tool_result = test_db_session.execute(tool_query).scalar_one_or_none()
        assert tool_result is not None
        assert tool_result.name == "test-tool-resilient"

        # Verify no audit entry was created (audit failed)
        audit_query = select(AuditTrail).where(
            AuditTrail.resource_type == "tool",
            AuditTrail.resource_id == tool.id,
        )
        audit_result = test_db_session.execute(audit_query).scalar_one_or_none()
        assert audit_result is None

    def test_audit_and_main_resource_both_persist(self, test_db_session, audit_service):
        """Verify both audit and main resource transactions complete independently.

        This test validates transaction isolation:
        1. Main resource commits in request-scoped session
        2. Audit entry commits in separate session
        3. Both persist independently
        4. Querying either record succeeds
        """
        # Create a tool directly in the main session
        tool = Tool(
            id="tool-789",
            original_name="test-tool-independent",
            name="test-tool-independent",
            description="Test tool for independent persistence",
            input_schema={"type": "object"},
            gateway_id="gw-1",
            team_id="public",
        )
        test_db_session.add(tool)
        test_db_session.commit()

        # Call audit service (creates separate session)
        audit_entry = audit_service.log_action(
            action="CREATE",
            resource_type="tool",
            resource_id=tool.id,
            user_id="test-user@example.com",
            resource_name=tool.name,
            db=None,
        )

        assert audit_entry is not None

        # Close and reopen session to ensure we're reading from database
        test_db_session.close()
        from mcpgateway.db import SessionLocal

        fresh_session = SessionLocal()
        try:
            # Verify tool persisted
            tool_query = select(Tool).where(Tool.id == tool.id)
            tool_result = fresh_session.execute(tool_query).scalar_one_or_none()
            assert tool_result is not None
            assert tool_result.name == "test-tool-independent"

            # Verify audit entry persisted
            audit_query = select(AuditTrail).where(
                AuditTrail.resource_type == "tool",
                AuditTrail.resource_id == tool.id,
                AuditTrail.action == "CREATE",
            )
            audit_result = fresh_session.execute(audit_query).scalar_one_or_none()
            assert audit_result is not None
            assert audit_result.user_id == "test-user@example.com"
            assert audit_result.success is True

            # Verify they are independent records
            assert tool_result.id == audit_result.resource_id
        finally:
            fresh_session.close()

    def test_audit_service_creates_own_session_when_none_provided(self, test_db_session, audit_service):
        """Verify audit service creates its own session when db parameter is None.

        This test validates the core separate session behavior:
        1. Call log_action without db parameter
        2. Audit service creates its own SessionLocal()
        3. Audit entry persists
        """
        # Call log_action without providing db parameter
        audit_entry = audit_service.log_action(
            action="TEST_ACTION",
            resource_type="test_resource",
            resource_id="test-123",
            user_id="test-user@example.com",
            db=None,  # Explicitly pass None to trigger separate session creation
        )

        # Verify audit entry was created and returned
        assert audit_entry is not None

        # Verify audit entry persisted in database
        audit_query = select(AuditTrail).where(
            AuditTrail.resource_type == "test_resource",
            AuditTrail.resource_id == "test-123",
            AuditTrail.action == "TEST_ACTION",
        )
        audit_result = test_db_session.execute(audit_query).scalar_one_or_none()
        assert audit_result is not None
        assert audit_result.user_id == "test-user@example.com"

    def test_main_session_rollback_does_not_affect_audit(self, test_db_session, audit_service):
        """Verify that rolling back main session does not affect audit entries.

        This test validates transaction isolation in failure scenarios:
        1. Create tool (triggers audit)
        2. Rollback main session
        3. Tool does not persist
        4. Audit entry still persists (separate transaction)
        """
        # Create a tool directly in the main session
        tool = Tool(
            id="tool-rollback",
            original_name="test-tool-rollback",
            name="test-tool-rollback",
            description="Test tool for rollback isolation",
            input_schema={"type": "object"},
            gateway_id="gw-1",
            team_id="public",
        )
        test_db_session.add(tool)

        # Call audit service BEFORE committing (creates separate session)
        audit_entry = audit_service.log_action(
            action="CREATE",
            resource_type="tool",
            resource_id=tool.id,
            user_id="test-user@example.com",
            resource_name=tool.name,
            db=None,
        )

        assert audit_entry is not None

        # Rollback the main session (simulating a failure)
        test_db_session.rollback()

        # Verify tool does NOT exist in database
        tool_query = select(Tool).where(Tool.id == tool.id)
        tool_result = test_db_session.execute(tool_query).scalar_one_or_none()
        assert tool_result is None

        # Verify audit entry DOES exist (separate transaction committed)
        audit_query = select(AuditTrail).where(
            AuditTrail.resource_type == "tool",
            AuditTrail.resource_id == tool.id,
            AuditTrail.action == "CREATE",
        )
        audit_result = test_db_session.execute(audit_query).scalar_one_or_none()
        assert audit_result is not None
        assert audit_result.user_id == "test-user@example.com"
        assert audit_result.success is True


class TestAuditTrailSessionLifecycle:
    """Tests for audit trail session lifecycle management."""

    def test_audit_service_closes_own_session(self, audit_service, monkeypatch):
        """Verify audit service properly closes its own session.

        This test validates resource cleanup:
        1. Audit service creates session
        2. Session is closed after use
        3. No session leaks
        """
        # Track session lifecycle
        session_created = False
        session_closed = False

        class MockSession:
            def __init__(self):
                nonlocal session_created
                session_created = True
                self.committed = False
                self.rolled_back = False

            def add(self, obj):
                pass

            def commit(self):
                self.committed = True

            def refresh(self, obj):
                pass

            def rollback(self):
                self.rolled_back = True

            def close(self):
                nonlocal session_closed
                session_closed = True

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.close()

        # Patch SessionLocal to return our mock
        monkeypatch.setattr("mcpgateway.services.audit_trail_service.SessionLocal", MockSession)
        monkeypatch.setattr("mcpgateway.services.audit_trail_service.AuditTrail", lambda **kwargs: MagicMock())

        # Call log_action without db parameter
        audit_service.log_action(
            action="TEST_ACTION",
            resource_type="test_resource",
            resource_id="test-123",
            user_id="test-user@example.com",
            db=None,
        )

        # Verify session was created and closed
        assert session_created is True
        assert session_closed is True

    def test_audit_service_handles_session_exception(self, audit_service, monkeypatch):
        """Verify audit service handles session exceptions gracefully.

        This test validates error handling:
        1. Session operation raises exception
        2. Exception is caught and logged
        3. Session is rolled back and closed
        4. log_action returns None
        """
        session_rolled_back = False
        session_closed = False

        class FailingSession:
            def __init__(self):
                pass

            def add(self, obj):
                raise RuntimeError("Simulated session failure")

            def commit(self):
                pass

            def refresh(self, obj):
                pass

            def rollback(self):
                nonlocal session_rolled_back
                session_rolled_back = True

            def close(self):
                nonlocal session_closed
                session_closed = True

        # Patch SessionLocal to return failing session
        monkeypatch.setattr("mcpgateway.services.audit_trail_service.SessionLocal", FailingSession)
        monkeypatch.setattr("mcpgateway.services.audit_trail_service.AuditTrail", lambda **kwargs: MagicMock())

        # Call log_action - should handle exception gracefully
        result = audit_service.log_action(
            action="TEST_ACTION",
            resource_type="test_resource",
            resource_id="test-123",
            user_id="test-user@example.com",
            db=None,
        )

        # Verify exception was handled
        assert result is None
        assert session_rolled_back is True
        assert session_closed is True


class TestCrossServiceAuditBehavior:
    """Integration tests that exercise the full service call stack.

    Unlike TestAuditTrailSeparateSession (which calls log_action directly),
    these tests invoke ToolService and ResourceService end-to-end so that
    audit writes happen as a side-effect of the service operation — the
    same path taken in production.

    Scenarios verified:
    1. A successful tool registration produces an AuditTrail row committed in
       its own session, independently of the tool's session.
    2. A successful resource registration produces an AuditTrail row.
    3. When the audit DB session factory raises on creation, the main resource
       is still committed and no exception propagates to the caller.
    """

    async def test_tool_service_register_creates_audit_entry(self, test_db_engine, test_db_session):
        """Creating a tool via ToolService writes an audit entry in a separate session.

        Steps:
        1. Call ToolService.register_tool() with a minimal ToolCreate payload.
        2. Open a fresh session to read back the Tool and AuditTrail rows.
        3. Assert both rows exist and the AuditTrail references the correct resource_id.
        """
        tool_service = ToolService()

        tool_payload = ToolCreate(
            name="cross-service-tool",
            url="http://example.com/tool",
            description="Tool for cross-service audit test",
            integration_type="REST",
            request_type="POST",
            input_schema={"type": "object"},
        )

        with patch.object(tool_service, "_notify_tool_added", new_callable=AsyncMock):
            TestSessionLocal = sessionmaker(bind=test_db_engine)
            db = TestSessionLocal()
            try:
                result = await tool_service.register_tool(
                    db=db,
                    tool=tool_payload,
                    created_by="auditor@example.com",
                    owner_email="auditor@example.com",
                )
            finally:
                db.close()

        assert result is not None
        assert result.name == "cross-service-tool"

        # Verify both rows via a fresh session (isolates from above transactions)
        fresh_session = sessionmaker(bind=test_db_engine)()
        try:
            tool_row = fresh_session.execute(select(Tool).where(Tool.name == "cross-service-tool")).scalar_one_or_none()
            assert tool_row is not None, "Tool row missing after register_tool()"

            audit_row = fresh_session.execute(
                select(AuditTrail).where(
                    AuditTrail.resource_type == "tool",
                    AuditTrail.action == "create_tool",
                    AuditTrail.resource_id == str(tool_row.id),
                )
            ).scalar_one_or_none()
            assert audit_row is not None, "AuditTrail row missing after register_tool()"
            assert audit_row.user_id == "auditor@example.com"
            assert audit_row.success is True
        finally:
            fresh_session.close()

    async def test_resource_service_register_creates_audit_entry(self, test_db_engine, test_db_session):
        """Creating a resource via ResourceService writes an audit entry in a separate session."""
        resource_service = ResourceService()

        resource_payload = ResourceCreate(
            uri="resource://cross-service-test/doc.txt",
            name="cross-service-resource",
            description="Resource for cross-service audit test",
            content="hello world",
            mime_type="text/plain",
        )

        with patch.object(resource_service, "_notify_resource_added", new_callable=AsyncMock):
            TestSessionLocal = sessionmaker(bind=test_db_engine)
            db = TestSessionLocal()
            try:
                result = await resource_service.register_resource(
                    db=db,
                    resource=resource_payload,
                    created_by="auditor@example.com",
                    owner_email="auditor@example.com",
                )
            finally:
                db.close()

        assert result is not None
        assert result.name == "cross-service-resource"

        fresh_session = sessionmaker(bind=test_db_engine)()
        try:
            resource_row = fresh_session.execute(select(Resource).where(Resource.name == "cross-service-resource")).scalar_one_or_none()
            assert resource_row is not None, "Resource row missing after register_resource()"

            audit_row = fresh_session.execute(
                select(AuditTrail).where(
                    AuditTrail.resource_type == "resource",
                    AuditTrail.action == "create_resource",
                    AuditTrail.resource_id == str(resource_row.id),
                )
            ).scalar_one_or_none()
            assert audit_row is not None, "AuditTrail row missing after register_resource()"
            assert audit_row.user_id == "auditor@example.com"
            assert audit_row.success is True
        finally:
            fresh_session.close()

    async def test_tool_service_register_survives_audit_failure(self, test_db_engine, test_db_session):
        """A failing audit session must not prevent the tool row from being committed.

        Simulates an unreachable audit DB by patching SessionLocal in
        audit_trail_service to raise on construction.  The tool registration
        must complete without raising, the Tool row must persist, and no
        AuditTrail row should exist.
        """
        tool_service = ToolService()

        tool_payload = ToolCreate(
            name="resilient-tool",
            url="http://example.com/resilient",
            description="Tool for audit-failure resilience test",
            integration_type="REST",
            request_type="POST",
            input_schema={"type": "object"},
        )

        with (
            patch.object(tool_service, "_notify_tool_added", new_callable=AsyncMock),
            patch(
                "mcpgateway.services.audit_trail_service.SessionLocal",
                side_effect=RuntimeError("audit DB unavailable"),
            ),
        ):
            TestSessionLocal = sessionmaker(bind=test_db_engine)
            db = TestSessionLocal()
            try:
                result = await tool_service.register_tool(
                    db=db,
                    tool=tool_payload,
                    created_by="auditor@example.com",
                    owner_email="auditor@example.com",
                )
            finally:
                db.close()

        # Service must complete without raising
        assert result is not None
        assert result.name == "resilient-tool"

        fresh_session = sessionmaker(bind=test_db_engine)()
        try:
            tool_row = fresh_session.execute(select(Tool).where(Tool.name == "resilient-tool")).scalar_one_or_none()
            assert tool_row is not None, "Tool row was not committed despite audit failure"

            audit_row = fresh_session.execute(
                select(AuditTrail).where(
                    AuditTrail.resource_type == "tool",
                    AuditTrail.resource_id == str(tool_row.id),
                )
            ).scalar_one_or_none()
            assert audit_row is None, "AuditTrail row should not exist when audit session creation fails"
        finally:
            fresh_session.close()
