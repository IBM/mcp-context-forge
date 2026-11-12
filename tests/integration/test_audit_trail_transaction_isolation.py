# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_audit_trail_transaction_isolation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Integration tests for audit trail transaction isolation.

Tests verify that audit trail uses separate database sessions and that
main resource operations commit successfully even when audit logging fails.
This validates the separate session pattern documented in AGENTS.md.
"""

# Standard
from collections import Counter
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import AuditTrail, Base, EmailTeam, EmailTeamMember, EmailUser, Gateway, Prompt, Resource, Server, Tool
from mcpgateway.routers import log_search
from mcpgateway.schemas import PromptCreate, ResourceCreate, ServerCreate, ServerUpdate, ToolCreate
from mcpgateway.services.audit_trail_service import AuditTrailService
from mcpgateway.services.gateway_service import GatewayService
from mcpgateway.services.import_service import ConflictStrategy, ImportService
from mcpgateway.services.prompt_service import PromptService
from mcpgateway.services.resource_service import ResourceService
from mcpgateway.services.server_service import ServerService
from mcpgateway.services.tool_service import ToolService

TEAM_A = "00000000000040008000000000000001"
TEAM_B = "00000000000040008000000000000002"


def _import_entity(entity_type, name):
    """Build a configuration entity for an audit regression.

    Args:
        entity_type: Imported entity collection name.
        name: Unique resource name.

    Returns:
        Import payload without ownership fields.
    """
    entity = {"name": name, "description": "Imported resource"}
    if entity_type == "tools":
        entity.update(url="http://example.com/tool", integration_type="REST", jsonpath_filter="")
    elif entity_type == "resources":
        entity.update(uri=f"resource://audit/{name}", content="hello", mime_type="text/plain")
    elif entity_type == "prompts":
        entity.update(template="Hello", arguments=[])
    return entity


def _existing_bulk_resource(entity_type, name, owner, team):
    """Build an existing public resource with explicit persisted ownership.

    Args:
        entity_type: Bulk resource collection name.
        name: Unique resource name.
        owner: Persisted owner email.
        team: Persisted team ID or None.

    Returns:
        Resource ORM instance with stable ownership and import metadata.
    """
    values = {"name": name, "description": "Before import", "owner_email": owner, "team_id": team, "visibility": "public", "created_by": owner, "created_via": "api"}
    if entity_type == "tools":
        return Tool(**values, original_name=name, url="http://example.com/tool", input_schema={"type": "object"}, integration_type="REST")
    if entity_type == "resources":
        return Resource(**values, uri=f"resource://audit/{name}", mime_type="text/plain")
    return Prompt(**values, original_name=name, template="Hello", argument_schema={"type": "object", "properties": {}})


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


@pytest.fixture
def audit_actor(test_db_session):
    """Persist audit identities, teams, and target-owner memberships."""
    actor = "audit-actor@example.com"
    target = "audit-target@example.com"
    test_db_session.add_all([EmailUser(email=actor), EmailUser(email=target)])
    test_db_session.flush()
    test_db_session.add_all([EmailTeam(id=team_id, name=team_id, slug=team_id, created_by=actor) for team_id in (TEAM_A, TEAM_B)])
    test_db_session.flush()
    test_db_session.add_all([EmailTeamMember(team_id=team_id, user_email=target, role="member") for team_id in (TEAM_A, TEAM_B)])
    test_db_session.add_all([EmailTeamMember(team_id=team_id, user_email=actor, role="owner") for team_id in (TEAM_A, TEAM_B)])
    test_db_session.commit()
    return actor


@pytest.fixture
def server_service(monkeypatch):
    """Use real server persistence with isolated event notifications."""
    service = ServerService()
    for method in ("_notify_server_added", "_notify_server_updated", "_notify_server_activated", "_notify_server_deactivated", "_notify_server_deleted"):
        monkeypatch.setattr(service, method, AsyncMock())
    return service


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

    @pytest.mark.parametrize(("schema_team", "request_team", "expected_team"), [(None, None, None), (None, TEAM_A, TEAM_A), (TEAM_A, None, None), (TEAM_A, TEAM_B, TEAM_B)])
    async def test_server_lifecycle_audits_persisted_team(self, test_db_engine, test_db_session, audit_actor, server_service, schema_team, request_team, expected_team):
        """Server lifecycle audits use persisted teams before and after reassignment."""
        result = await server_service.register_server(
            test_db_session,
            ServerCreate(name="audit-server", team_id=schema_team),
            team_id=request_team,
            owner_email=audit_actor,
            created_by=audit_actor,
        )
        server_id = result.id
        with sessionmaker(bind=test_db_engine)() as fresh:
            assert fresh.get(Server, server_id).team_id == expected_team
            row = fresh.execute(select(AuditTrail).where(AuditTrail.action == "create_server", AuditTrail.resource_id == server_id)).scalar_one()
            assert row.team_id == expected_team
            assert row.context["details"]["team_id"] == expected_team

        await server_service.update_server(test_db_session, server_id, ServerUpdate(team_id=TEAM_B), user_email=audit_actor)
        await server_service.set_server_state(test_db_session, server_id, activate=False, user_email=audit_actor)
        await server_service.set_server_state(test_db_session, server_id, activate=True, user_email=audit_actor)
        await server_service.delete_server(test_db_session, server_id, user_email=audit_actor)

        with sessionmaker(bind=test_db_engine)() as fresh:
            assert fresh.get(Server, server_id) is None
            rows = fresh.execute(select(AuditTrail).where(AuditTrail.resource_id == server_id)).scalars().all()
            assert {row.action: row.team_id for row in rows} == {
                "create_server": expected_team,
                "update_server": TEAM_B,
                "deactivate_server": TEAM_B,
                "activate_server": TEAM_B,
                "delete_server": TEAM_B,
            }

    @pytest.mark.parametrize(("schema_teams", "request_team"), [([TEAM_A, TEAM_B, None], None), ([TEAM_A, TEAM_A], None), ([TEAM_B, None], TEAM_A)])
    async def test_bulk_creation_audits_actual_tool_teams(self, test_db_engine, test_db_session, audit_actor, schema_teams, request_team):
        """Bulk creation groups persisted teams from request parameters and tool schemas."""
        payloads = [ToolCreate(name=f"audit_bulk_{index}", url="http://example.com/tool", team_id=team_id) for index, team_id in enumerate(schema_teams)]
        stats = await ToolService().register_tools_bulk(test_db_session, payloads, created_by=audit_actor, owner_email=audit_actor, team_id=request_team, import_batch_id="audit-batch-create")
        assert stats["created"] == len(payloads)
        assert stats["failed"] == 0, stats["errors"]

        with sessionmaker(bind=test_db_engine)() as fresh:
            tools = fresh.execute(select(Tool)).scalars().all()
            expected_counts = Counter([request_team] * len(schema_teams))
            assert Counter(tool.team_id for tool in tools) == expected_counts
            rows = fresh.execute(select(AuditTrail).where(AuditTrail.action == "bulk_create_tools")).scalars().all()
            assert len(rows) == len(expected_counts)
            assert {row.team_id: row.context["details"]["count"] for row in rows} == dict(expected_counts)
            assert all(row.context["details"]["import_batch_id"] == "audit-batch-create" for row in rows)

    async def test_mixed_bulk_updates_audit_existing_teams(self, test_db_engine, test_db_session, audit_actor):
        """Bulk updates retain existing teams and group new tools with the correct operation and count."""
        test_db_session.add_all(
            [
                Tool(name=name, original_name=name, url="http://example.com/tool", team_id=team_id, owner_email=audit_actor, visibility="public", input_schema={"type": "object"})
                for name, team_id in (("existinga", TEAM_A), ("existingb", TEAM_B), ("existingnull", None))
            ]
        )
        test_db_session.commit()
        payloads = [ToolCreate(name=name, url="http://example.com/updated", team_id=TEAM_B) for name in ("existinga", "existingb", "existingnull", "newb")]
        stats = await ToolService().register_tools_bulk(
            test_db_session, payloads, created_by=audit_actor, owner_email=audit_actor, team_id=TEAM_B, conflict_strategy="update", import_batch_id="audit-batch-mixed", user_email=audit_actor
        )
        assert (stats["created"], stats["updated"], stats["failed"]) == (1, 3, 0), stats["errors"]

        with sessionmaker(bind=test_db_engine)() as fresh:
            assert {tool.original_name: tool.team_id for tool in fresh.execute(select(Tool)).scalars()} == {"existinga": TEAM_A, "existingb": TEAM_B, "existingnull": None, "newb": TEAM_B}
            rows = fresh.execute(select(AuditTrail)).scalars().all()
            assert len(rows) == 3
            assert {row.team_id: (row.action, row.context["details"]["count"]) for row in rows} == {TEAM_A: ("bulk_update_tools", 1), TEAM_B: ("bulk_create_tools", 2), None: ("bulk_update_tools", 1)}
            assert all(row.context["details"]["import_batch_id"] == "audit-batch-mixed" for row in rows)

    @pytest.mark.parametrize("target_team", [None, TEAM_B])
    async def test_gateway_transfer_audits_resulting_team(self, test_db_engine, test_db_session, audit_actor, target_team):
        """Gateway ownership transfers persist retained and destination teams in audit rows."""
        gateway = Gateway(id="audit-gateway", name="audit-gateway", slug="audit-gateway", url="https://example.com/mcp", capabilities={}, team_id=TEAM_A, visibility="team", owner_email=audit_actor)
        test_db_session.add(gateway)
        test_db_session.commit()
        await GatewayService().transfer_gateway_ownership(test_db_session, gateway.id, "audit-target@example.com", audit_actor, target_team_id=target_team)

        with sessionmaker(bind=test_db_engine)() as fresh:
            expected_team = target_team or TEAM_A
            assert fresh.get(Gateway, "audit-gateway").team_id == expected_team
            row = fresh.execute(select(AuditTrail).where(AuditTrail.action == "gateway.transfer_ownership", AuditTrail.resource_id == "audit-gateway")).scalar_one()
            assert row.team_id == expected_team

    @pytest.mark.parametrize("has_personal_team", [True, False])
    @pytest.mark.parametrize(("entity_type", "model"), [("tools", Tool), ("resources", Resource), ("prompts", Prompt), ("servers", Server)])
    async def test_configuration_import_audits_trusted_personal_team(self, test_db_engine, test_db_session, audit_actor, server_service, has_personal_team, entity_type, model):
        """Configuration imports stamp the trusted personal team before post-import assignment and ignore payload ownership."""
        if has_personal_team:
            test_db_session.get(EmailTeam, TEAM_A).is_personal = True
            test_db_session.commit()
        entity = {**_import_entity(entity_type, "importresource"), "team_id": TEAM_B, "owner_email": "audit-target@example.com", "visibility": "public"}
        payload = {
            "version": "2025-03-26",
            "exported_at": "2025-01-01T00:00:00Z",
            "entities": {entity_type: [entity]},
        }
        service = ImportService()
        service.server_service = server_service
        status = await service.import_configuration(test_db_session, payload, imported_by=audit_actor)
        assert status.created_entities == 1
        assert status.failed_entities == 0, status.errors

        with sessionmaker(bind=test_db_engine)() as fresh:
            expected_team = TEAM_A if has_personal_team else None
            resource = fresh.execute(select(model)).scalar_one()
            assert resource.team_id == expected_team
            assert resource.owner_email == audit_actor
            assert resource.visibility == ("team" if has_personal_team else "public")
            action = "create_server" if entity_type == "servers" else f"bulk_create_{entity_type}"
            row = fresh.execute(select(AuditTrail).where(AuditTrail.action == action)).scalar_one()
            assert row.team_id == expected_team
            if entity_type == "tools":
                assert row.context["details"]["count"] == 1
                assert row.context["details"]["import_batch_id"]

    @pytest.mark.parametrize(("entity_type", "model"), [("tools", Tool), ("resources", Resource), ("prompts", Prompt)])
    async def test_configuration_import_updates_audit_existing_team(self, test_db_engine, test_db_session, audit_actor, entity_type, model):
        """Configuration imports retain the existing resource team when the importer has a different personal team."""
        test_db_session.get(EmailTeam, TEAM_A).is_personal = True
        test_db_session.add(_existing_bulk_resource(entity_type, "existingimport", audit_actor, TEAM_B))
        test_db_session.commit()
        service = ImportService()
        status = await service.import_configuration(
            test_db_session,
            {
                "version": "2025-03-26",
                "exported_at": "2025-01-01T00:00:00Z",
                "entities": {entity_type: [_import_entity(entity_type, "existingimport")]},
            },
            imported_by=audit_actor,
        )
        assert (status.updated_entities, status.failed_entities) == (1, 0), status.errors

        with sessionmaker(bind=test_db_engine)() as fresh:
            resource = fresh.execute(select(model)).scalar_one()
            assert resource.team_id == TEAM_B
            assert resource.owner_email == audit_actor
            assert resource.description == "Imported resource"
            row = fresh.execute(select(AuditTrail).where(AuditTrail.action == f"bulk_update_{entity_type}")).scalar_one()
            assert row.team_id == TEAM_B

    @pytest.mark.parametrize(("entity_type", "model", "schema", "service_type"), [("resources", Resource, ResourceCreate, ResourceService), ("prompts", Prompt, PromptCreate, PromptService)])
    async def test_mixed_bulk_resource_audits_use_group_local_counts(self, test_db_engine, test_db_session, audit_actor, entity_type, model, schema, service_type):
        """Resource and prompt audits separate new ownership from existing teams without changing payload conventions."""
        existing = [("existinga", TEAM_A), ("existingb", TEAM_B), ("existingnull", None)]
        test_db_session.add_all([_existing_bulk_resource(entity_type, name, audit_actor, team) for name, team in existing])
        test_db_session.commit()
        payloads = [schema(**_import_entity(entity_type, name)) for name in ("existinga", "existingb", "existingnull", "newa")]

        stats = await getattr(service_type(), f"register_{entity_type}_bulk")(
            test_db_session, payloads, created_by=audit_actor, owner_email=audit_actor, user_email=audit_actor, team_id=TEAM_A, conflict_strategy="update", import_batch_id="mixed-batch"
        )

        assert (stats["created"], stats["updated"], stats["failed"]) == (1, 3, 0), stats["errors"]
        with sessionmaker(bind=test_db_engine)() as fresh:
            assert {resource.name: resource.team_id for resource in fresh.execute(select(model)).scalars()} == {**dict(existing), "newa": TEAM_A}
            rows = fresh.execute(select(AuditTrail)).scalars().all()
            assert len(rows) == 3
            assert {row.team_id: (row.action, row.new_values[f"{entity_type}_created"], row.new_values[f"{entity_type}_updated"]) for row in rows} == {
                TEAM_A: (f"bulk_create_{entity_type}", 1, 1),
                TEAM_B: (f"bulk_update_{entity_type}", 0, 1),
                None: (f"bulk_update_{entity_type}", 0, 1),
            }
            assert all(row.resource_id == "mixed-batch" and row.context["import_batch_id"] == "mixed-batch" for row in rows)

    @pytest.mark.parametrize(
        ("entity_type", "model", "schema", "service_type"),
        [("tools", Tool, ToolCreate, ToolService), ("resources", Resource, ResourceCreate, ResourceService), ("prompts", Prompt, PromptCreate, PromptService)],
    )
    @pytest.mark.parametrize("has_identity", [True, False])
    async def test_bulk_audits_exclude_denied_updates(self, test_db_engine, test_db_session, audit_actor, entity_type, model, schema, service_type, has_identity):
        """Foreign-owner and identity-less updates leave persisted resources unchanged and emit no success audit."""
        test_db_session.add(_existing_bulk_resource(entity_type, "foreignresource", "audit-target@example.com", TEAM_B))
        test_db_session.commit()

        stats = await getattr(service_type(), f"register_{entity_type}_bulk")(
            test_db_session,
            [schema(**_import_entity(entity_type, "foreignresource"))],
            created_by=audit_actor,
            user_email=audit_actor if has_identity else None,
            team_id=TEAM_A,
            conflict_strategy="update",
        )

        assert (stats["created"], stats["updated"], stats["failed"]) == (0, 0, 1), stats["errors"]
        with sessionmaker(bind=test_db_engine)() as fresh:
            resource = fresh.execute(select(model)).scalar_one()
            assert (resource.description, resource.owner_email, resource.team_id) == ("Before import", "audit-target@example.com", TEAM_B)
            assert fresh.execute(select(AuditTrail)).scalars().all() == []

    @pytest.mark.parametrize(("entity_type", "model"), [("resources", Resource), ("prompts", Prompt)])
    async def test_configuration_import_rename_audits_new_team(self, test_db_engine, test_db_session, audit_actor, entity_type, model):
        """Conflict renames audit the new personal-team resource and preserve existing ownership."""
        test_db_session.get(EmailTeam, TEAM_A).is_personal = True
        existing = _existing_bulk_resource(entity_type, "renamedimport", audit_actor, TEAM_B)
        test_db_session.add(existing)
        test_db_session.commit()
        existing_id = existing.id
        payload = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {entity_type: [_import_entity(entity_type, "renamedimport")]}}

        status = await ImportService().import_configuration(test_db_session, payload, conflict_strategy=ConflictStrategy.RENAME, imported_by=audit_actor)

        assert (status.created_entities, status.updated_entities, status.failed_entities) == (1, 0, 0), status.errors
        with sessionmaker(bind=test_db_engine)() as fresh:
            original = fresh.get(model, existing_id)
            assert (original.description, original.team_id, original.owner_email) == ("Before import", TEAM_B, audit_actor)
            renamed = fresh.execute(select(model).where(model.id != existing_id)).scalar_one()
            assert (renamed.team_id, renamed.owner_email, renamed.visibility) == (TEAM_A, audit_actor, "team")
            row = fresh.execute(select(AuditTrail).where(AuditTrail.action == f"bulk_create_{entity_type}")).scalar_one()
            assert row.team_id == TEAM_A
            assert row.new_values[f"{entity_type}_created"] == 1
            assert row.new_values[f"{entity_type}_updated"] == 0

    @pytest.mark.parametrize("strategy", list(ConflictStrategy))
    @pytest.mark.parametrize(("same_owner", "same_team"), [(True, False), (False, True), (False, False)])
    @pytest.mark.parametrize("has_owned", [True, False])
    async def test_server_import_conflicts_preserve_scope(self, test_db_engine, test_db_session, audit_actor, server_service, strategy, same_owner, same_team, has_owned):
        """Server imports resolve same-scope conflicts without modifying same-name foreign resources."""
        test_db_session.get(EmailTeam, TEAM_A).is_personal = True
        test_db_session.commit()
        owned = None
        if has_owned:
            owned = await server_service.register_server(test_db_session, ServerCreate(name="conflictserver", description="Before import"), created_by=audit_actor, team_id=TEAM_A, visibility="team")
        foreign = await server_service.register_server(
            test_db_session,
            ServerCreate(name="conflictserver", description="Foreign resource"),
            created_by=audit_actor if same_owner else "audit-target@example.com",
            team_id=TEAM_A if same_team else TEAM_B,
            visibility="team",
        )
        service = ImportService()
        service.server_service = server_service
        payload = {"version": "2025-03-26", "exported_at": "2025-01-01T00:00:00Z", "entities": {"servers": [_import_entity("servers", "conflictserver")]}}

        status = await service.import_configuration(test_db_session, payload, conflict_strategy=strategy, imported_by=audit_actor)

        with sessionmaker(bind=test_db_engine)() as fresh:
            assert fresh.get(Server, foreign.id).description == "Foreign resource"
            if not has_owned:
                assert (status.created_entities, status.updated_entities, status.failed_entities) == (1, 0, 0), status.errors
                created = fresh.execute(select(Server).where(Server.id != foreign.id)).scalar_one()
                assert (created.team_id, created.owner_email, created.visibility) == (TEAM_A, audit_actor, "team")
                row = fresh.execute(select(AuditTrail).where(AuditTrail.resource_id == created.id, AuditTrail.action == "create_server")).scalar_one()
                assert row.team_id == TEAM_A
                return
            assert fresh.get(Server, owned.id).team_id == TEAM_A
            assert fresh.get(Server, owned.id).owner_email == audit_actor
            expected = "Imported resource" if strategy == ConflictStrategy.UPDATE else "Before import"
            assert fresh.get(Server, owned.id).description == expected
            if strategy == ConflictStrategy.RENAME:
                assert status.created_entities == 1
                renamed = fresh.execute(select(Server).where(Server.name.like("conflictserver_imported_%"))).scalar_one()
                assert (renamed.team_id, renamed.owner_email, renamed.visibility) == (TEAM_A, audit_actor, "team")
                row = fresh.execute(select(AuditTrail).where(AuditTrail.resource_id == renamed.id, AuditTrail.action == "create_server")).scalar_one()
                assert row.team_id == TEAM_A
            elif strategy == ConflictStrategy.UPDATE:
                assert status.updated_entities == 1
                row = fresh.execute(select(AuditTrail).where(AuditTrail.resource_id == owned.id, AuditTrail.action == "update_server")).scalar_one()
                assert row.team_id == TEAM_A
            elif strategy == ConflictStrategy.SKIP:
                assert status.skipped_entities == 1
            else:
                assert status.failed_entities == 1

    @pytest.mark.parametrize("entity_type", ["tools", "resources", "prompts"])
    @pytest.mark.parametrize("expire_on_commit", [False, True])
    async def test_bulk_update_audit_query_budget(self, test_db_engine, test_db_session, audit_actor, entity_type, expire_on_commit):
        """Audit grouping adds no per-updated-resource SELECTs under either session expiry mode."""
        services = {"tools": ToolService, "resources": ResourceService, "prompts": PromptService}
        schemas = {"tools": ToolCreate, "resources": ResourceCreate, "prompts": PromptCreate}
        counts = []
        for size in (1, 8):
            names = [f"budget{size}resource{index}" for index in range(size)]
            test_db_session.add_all([_existing_bulk_resource(entity_type, name, audit_actor, TEAM_B) for name in names])
            test_db_session.commit()
            selects = []

            def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
                normalized = " ".join(statement.lower().split())
                if normalized.startswith("select") and f"from {entity_type}" in normalized:
                    selects.append(statement)

            event.listen(test_db_engine, "before_cursor_execute", capture)
            try:
                with sessionmaker(bind=test_db_engine, expire_on_commit=expire_on_commit)() as session:
                    service = services[entity_type]()
                    stats = await getattr(service, f"register_{entity_type}_bulk")(
                        session,
                        [schemas[entity_type](**_import_entity(entity_type, name)) for name in names],
                        created_by=audit_actor,
                        owner_email=audit_actor,
                        user_email=audit_actor,
                        team_id=TEAM_A,
                        conflict_strategy="update",
                        import_batch_id=f"query-budget-{size}",
                    )
                assert (stats["updated"], stats["failed"]) == (size, 0), stats["errors"]
                counts.append(len(selects))
            finally:
                event.remove(test_db_engine, "before_cursor_execute", capture)
        assert counts[0] == counts[1], counts
        assert counts[1] <= 2, counts
        with sessionmaker(bind=test_db_engine)() as fresh:
            rows = fresh.execute(select(AuditTrail).where(AuditTrail.action == f"bulk_update_{entity_type}")).scalars().all()
            assert len(rows) == 2
            assert all(row.team_id == TEAM_B for row in rows)

    async def test_actor_feed_scopes_persisted_server_and_bulk_rows(self, test_db_engine, test_db_session, audit_actor, server_service, audit_service, monkeypatch):
        """One actor sees matching-team audits and its platform rows across differently scoped tokens."""
        server_ids = {}
        for team_id in (TEAM_A, TEAM_B):
            result = await server_service.register_server(test_db_session, ServerCreate(name=f"audit-{team_id}"), team_id=team_id, owner_email=audit_actor, created_by=audit_actor)
            server_ids[team_id] = result.id
        for index, team_id in enumerate((TEAM_A, TEAM_B)):
            stats = await ToolService().register_tools_bulk(
                test_db_session,
                [ToolCreate(name=f"feed_tool_{index}", url="http://example.com/tool")],
                created_by=audit_actor,
                owner_email=audit_actor,
                team_id=team_id,
                import_batch_id="audit-feed-batch",
            )
            assert stats["failed"] == 0, stats["errors"]
        audit_service.log_audit(user_id=audit_actor, user_email=audit_actor, resource_type="plugin", resource_id="platform-plugin", action="view")
        audit_service.log_audit(user_id="audit-target@example.com", user_email="audit-target@example.com", resource_type="plugin", resource_id="foreign-plugin", action="view")
        monkeypatch.setattr("mcpgateway.middleware.rbac.PermissionService.check_permission", AsyncMock(return_value=True))
        monkeypatch.setattr("mcpgateway.plugins.get_plugin_manager", AsyncMock(return_value=None))

        with sessionmaker(bind=test_db_engine)() as fresh:
            rows = fresh.execute(select(AuditTrail)).scalars().all()
            assert len(rows) == 6
            assert {row.resource_id: row.team_id for row in rows if row.resource_type == "plugin"} == {"platform-plugin": None, "foreign-plugin": None}
            server_rows = {row.resource_id: row for row in rows if row.action == "create_server"}
            assert {resource_id: row.team_id for resource_id, row in server_rows.items()} == {server_ids[TEAM_A]: TEAM_A, server_ids[TEAM_B]: TEAM_B}
            bulk_rows = {row.team_id: row for row in rows if row.action == "bulk_create_tools"}
            assert set(bulk_rows) == {TEAM_A, TEAM_B}
            assert all(row.context["details"] == {"count": 1, "import_batch_id": "audit-feed-batch"} for row in bulk_rows.values())
            team_a_ids = {f"audit:{server_rows[server_ids[TEAM_A]].id}", f"audit:{bulk_rows[TEAM_A].id}"}
            team_b_ids = {f"audit:{server_rows[server_ids[TEAM_B]].id}", f"audit:{bulk_rows[TEAM_B].id}"}
            platform_ids = {f"audit:{row.id}" for row in rows if row.resource_id == "platform-plugin"}
            expected_scopes = [([TEAM_A], team_a_ids | platform_ids), ([TEAM_B], team_b_ids | platform_ids), ([], platform_ids), (None, {f"audit:{row.id}" for row in rows})]
            for token_teams, expected_ids in expected_scopes:
                monkeypatch.setattr(log_search, "get_scoped_resource_access_context", lambda request, user, teams=token_teams: (audit_actor, teams))
                response = await log_search.get_activity_feed(request=MagicMock(), limit=50, since=None, user={"email": audit_actor, "db": fresh, "token_scopes": ["audit:read"]}, db=fresh)
                assert {item.id for item in response.items} == expected_ids

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
