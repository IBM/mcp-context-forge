"""
Comprehensive tests for IBM MCP Context Forge audit system.

Tests cover all components aligned with GitHub issue #2225.
"""

import asyncio
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
import json

from mcp_audit_models import (
    AuditDecisionRecord,
    SubjectDetails,
    ResourceDetails,
    ContextDetails,
    PolicyMatchDetails,
    DecisionResult,
    AuditQueryFilter,
    AuditConfig,
    SIEMConfig
)
from mcp_audit_database import SQLiteAuditDatabase, AuditDatabasePool
from mcp_audit_service import AuditService, create_audit_service


class TestRunner:
    """Simple test runner."""
    
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.tests = []
    
    def test(self, name):
        def decorator(func):
            self.tests.append((name, func))
            return func
        return decorator
    
    async def run(self):
        print("=" * 70)
        print("MCP Audit System Tests (GitHub Issue #2225)")
        print("=" * 70)
        
        for name, func in self.tests:
            try:
                print(f"\n▶ {name}...", end=" ")
                if asyncio.iscoroutinefunction(func):
                    await func()
                else:
                    func()
                print("✓ PASSED")
                self.passed += 1
            except AssertionError as e:
                print(f"✗ FAILED: {e}")
                self.failed += 1
            except Exception as e:
                print(f"✗ ERROR: {e}")
                self.failed += 1
        
        print("\n" + "=" * 70)
        print(f"Results: {self.passed} passed, {self.failed} failed")
        print("=" * 70)
        
        return self.failed == 0


runner = TestRunner()


# =============================================================================
# Model Tests
# =============================================================================

@runner.test("Create audit decision record")
def test_create_decision_record():
    """Test creating a comprehensive decision record."""
    subject = SubjectDetails(
        type="user",
        id="user-123",
        email="john.doe@example.com",
        roles=["developer", "admin"],
        teams=["engineering"],
        clearance_level=2
    )
    
    resource = ResourceDetails(
        type="tool",
        id="db-query",
        server="production-db",
        classification=4
    )
    
    context = ContextDetails(
        ip_address="10.0.0.50",
        user_agent="claude-desktop/1.0",
        mfa_verified=True,
        time_of_day="10:30"
    )
    
    policies = [
        PolicyMatchDetails(
            id="mac-policy-1",
            name="production-data-access",
            engine="mac",
            result="deny",
            explanation="User clearance (2) < Resource classification (4)"
        )
    ]
    
    record = AuditDecisionRecord(
        request_id="req-12345",
        gateway_node="gateway-1",
        subject=subject,
        action="tools.invoke",
        resource=resource,
        decision=DecisionResult.DENY,
        reason="Insufficient clearance level",
        matching_policies=policies,
        context=context,
        duration_ms=5.0
    )
    
    assert record.id is not None
    assert record.decision == DecisionResult.DENY
    assert record.subject.email == "john.doe@example.com"
    assert len(record.matching_policies) == 1


@runner.test("Convert record to dict (GitHub schema)")
def test_record_to_dict():
    """Test record conversion matches GitHub issue schema."""
    record = AuditDecisionRecord(
        request_id="req-123",
        gateway_node="gw-1",
        subject=SubjectDetails(type="user", id="u1", email="test@example.com"),
        action="read",
        resource=ResourceDetails(type="document", id="doc1"),
        decision=DecisionResult.ALLOW,
        reason="Policy allows"
    )
    
    data = record.to_dict()
    
    assert data['id'] is not None
    assert data['request_id'] == "req-123"
    assert data['gateway_node'] == "gw-1"
    assert data['subject']['email'] == "test@example.com"
    assert data['decision'] == "allow"


@runner.test("Convert to Splunk HEC format")
def test_splunk_hec_format():
    """Test Splunk HTTP Event Collector format."""
    record = AuditDecisionRecord(
        gateway_node="gw-1",
        subject=SubjectDetails(type="user", id="u1"),
        action="test",
        decision=DecisionResult.ALLOW
    )
    
    hec_data = record.to_splunk_hec()
    
    assert 'time' in hec_data
    assert 'host' in hec_data
    assert hec_data['host'] == "gw-1"
    assert hec_data['source'] == "mcp-policy-engine"
    assert hec_data['sourcetype'] == "policy_decision"
    assert 'event' in hec_data


@runner.test("Convert to Elasticsearch format")
def test_elasticsearch_format():
    """Test Elasticsearch document format."""
    record = AuditDecisionRecord(
        subject=SubjectDetails(type="user", id="u1"),
        action="test",
        decision=DecisionResult.ALLOW
    )
    
    es_doc = record.to_elasticsearch()
    
    assert '@timestamp' in es_doc
    assert es_doc['event_type'] == "policy_decision"


# =============================================================================
# Database Tests
# =============================================================================

@runner.test("Initialize SQLite database")
async def test_initialize_database():
    """Test database initialization creates schema."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = SQLiteAuditDatabase(Path(tmp_dir) / "test.db")
        await db.initialize()
        
        # Verify table exists
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_decisions'"
        )
        result = cursor.fetchone()
        assert result is not None


@runner.test("Store decision in database")
async def test_store_decision():
    """Test storing a decision record."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = SQLiteAuditDatabase(Path(tmp_dir) / "test.db")
        await db.initialize()
        
        record = AuditDecisionRecord(
            subject=SubjectDetails(type="user", id="u1", email="test@example.com"),
            action="read",
            resource=ResourceDetails(type="doc", id="d1"),
            decision=DecisionResult.ALLOW,
            reason="Policy allows"
        )
        
        await db.store_decision(record)
        
        # Verify stored
        cursor = db.conn.execute("SELECT COUNT(*) FROM audit_decisions")
        count = cursor.fetchone()[0]
        assert count == 1


@runner.test("Query decisions by subject")
async def test_query_by_subject():
    """Test querying decisions by subject."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = SQLiteAuditDatabase(Path(tmp_dir) / "test.db")
        await db.initialize()
        
        # Store multiple records
        for i in range(5):
            record = AuditDecisionRecord(
                subject=SubjectDetails(type="user", id=f"user{i % 2}", email=f"user{i%2}@example.com"),
                action=f"action{i}",
                decision=DecisionResult.ALLOW
            )
            await db.store_decision(record)
        
        # Query for user0
        filter = AuditQueryFilter(subject_id="user0")
        results = await db.query_decisions(filter)
        
        assert len(results) == 3  # indices 0, 2, 4
        assert all(r.subject.id == "user0" for r in results)


@runner.test("Query decisions by decision type")
async def test_query_by_decision():
    """Test querying by decision (allow/deny)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = SQLiteAuditDatabase(Path(tmp_dir) / "test.db")
        await db.initialize()
        
        # Store mixed decisions
        for i in range(10):
            decision = DecisionResult.DENY if i % 3 == 0 else DecisionResult.ALLOW
            record = AuditDecisionRecord(
                subject=SubjectDetails(type="user", id=f"u{i}"),
                action="test",
                decision=decision
            )
            await db.store_decision(record)
        
        # Query denials
        filter = AuditQueryFilter(decision=DecisionResult.DENY)
        results = await db.query_decisions(filter)
        
        assert len(results) == 4  # indices 0, 3, 6, 9
        assert all(r.decision == DecisionResult.DENY for r in results)


@runner.test("Query decisions by time range")
async def test_query_by_time_range():
    """Test querying by timestamp range."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = SQLiteAuditDatabase(Path(tmp_dir) / "test.db")
        await db.initialize()
        
        now = datetime.now(timezone.utc)
        
        # Store records at different times
        for i in range(5):
            record = AuditDecisionRecord(
                timestamp=now - timedelta(hours=i),
                subject=SubjectDetails(type="user", id=f"u{i}"),
                action="test",
                decision=DecisionResult.ALLOW
            )
            await db.store_decision(record)
        
        # Query last 2 hours
        filter = AuditQueryFilter(
            start_time=now - timedelta(hours=2),
            end_time=now
        )
        results = await db.query_decisions(filter)
        
        # Should get records from 0, 1, 2 hours ago
        assert len(results) == 3


@runner.test("Get statistics from database")
async def test_get_statistics():
    """Test calculating statistics."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = SQLiteAuditDatabase(Path(tmp_dir) / "test.db")
        await db.initialize()
        
        # Store varied records
        for i in range(20):
            decision = DecisionResult.ALLOW if i % 2 == 0 else DecisionResult.DENY
            record = AuditDecisionRecord(
                subject=SubjectDetails(type="user", id=f"user{i % 5}"),
                resource=ResourceDetails(type="doc", id=f"doc{i % 3}"),
                action="test",
                decision=decision,
                duration_ms=float(i * 2)
            )
            await db.store_decision(record)
        
        stats = await db.get_statistics()
        
        assert stats.total_decisions == 20
        assert stats.allowed == 10
        assert stats.denied == 10
        assert stats.unique_subjects == 5
        assert stats.unique_resources == 3
        assert stats.avg_duration_ms > 0


# =============================================================================
# Service Tests
# =============================================================================

@runner.test("Create audit service")
async def test_create_service():
    """Test creating audit service."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = create_audit_service(
            db_path=Path(tmp_dir) / "audit.db"
        )
        
        assert service is not None
        assert service.config.decisions_enabled is True
        
        await service.start()
        await service.stop()


@runner.test("Log allowed decision")
async def test_log_allowed():
    """Test logging an allowed access decision."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = create_audit_service(
            db_path=Path(tmp_dir) / "audit.db"
        )
        await service.start()
        
        subject = SubjectDetails(
            type="user",
            id="u1",
            email="test@example.com",
            roles=["developer"]
        )
        
        resource = ResourceDetails(
            type="api",
            id="user-service",
            server="prod"
        )
        
        context = ContextDetails(
            ip_address="192.168.1.1",
            mfa_verified=True
        )
        
        policies = [
            PolicyMatchDetails(
                id="rbac-1",
                name="Developer API Access",
                engine="rbac",
                result="allow",
                explanation="User has developer role"
            )
        ]
        
        record = await service.log_decision(
            decision=DecisionResult.ALLOW,
            action="api.call",
            subject=subject,
            resource=resource,
            reason="Policy allows",
            matching_policies=policies,
            context=context,
            request_id="req-123",
            duration_ms=3.5
        )
        
        assert record is not None
        assert record.decision == DecisionResult.ALLOW
        
        # Verify it was stored by querying for the subject
        filter = AuditQueryFilter(subject_id="u1")
        results = await service.get_db_pool().query_decisions(filter)
        assert len(results) == 1
        assert results[0].request_id == "req-123"
        
        await service.stop()


@runner.test("Log denied decision")
async def test_log_denied():
    """Test logging a denied access decision."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = create_audit_service(
            db_path=Path(tmp_dir) / "audit.db"
        )
        await service.start()
        
        subject = SubjectDetails(type="user", id="u1")
        resource = ResourceDetails(type="database", id="prod-db", classification=5)
        
        policies = [
            PolicyMatchDetails(
                id="mac-1",
                name="Classification Policy",
                engine="mac",
                result="deny",
                explanation="Insufficient clearance"
            )
        ]
        
        record = await service.log_decision(
            decision=DecisionResult.DENY,
            action="database.write",
            subject=subject,
            resource=resource,
            reason="User clearance too low",
            matching_policies=policies,
            duration_ms=2.1
        )
        
        assert record is not None
        assert record.decision == DecisionResult.DENY
        
        await service.stop()


@runner.test("Query via service")
async def test_query_via_service():
    """Test querying decisions through service."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = create_audit_service(
            db_path=Path(tmp_dir) / "audit.db"
        )
        await service.start()
        
        # Log multiple decisions
        for i in range(5):
            await service.log_decision(
                decision=DecisionResult.ALLOW,
                action=f"action{i}",
                subject=SubjectDetails(type="user", id=f"u{i}"),
                resource=ResourceDetails(type="doc", id=f"d{i}"),
                reason="test"
            )
        
        # Query all
        filter = AuditQueryFilter(limit=10)
        results = await service.get_db_pool().query_decisions(filter)
        
        assert len(results) == 5
        
        await service.stop()


@runner.test("Configuration controls logging")
async def test_configuration_controls():
    """Test that configuration controls what gets logged."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create service that doesn't log allowed decisions
        config = AuditConfig(
            decisions_enabled=True,
            log_allowed=False,  # Don't log allowed
            log_denied=True
        )
        service = AuditService(config, Path(tmp_dir) / "audit.db")
        await service.start()
        
        # Try to log allowed decision
        record = await service.log_decision(
            decision=DecisionResult.ALLOW,
            action="test",
            subject=SubjectDetails(type="user", id="u1"),
            resource=ResourceDetails(type="doc", id="d1"),
            reason="test"
        )
        
        # Should not be logged
        assert record is None
        
        # Log denied decision
        record = await service.log_decision(
            decision=DecisionResult.DENY,
            action="test",
            subject=SubjectDetails(type="user", id="u1"),
            resource=ResourceDetails(type="doc", id="d1"),
            reason="test"
        )
        
        # Should be logged
        assert record is not None
        
        await service.stop()


# =============================================================================
# Integration Tests
# =============================================================================

@runner.test("End-to-end: Log and query decision")
async def test_end_to_end():
    """Test complete workflow from logging to querying."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = create_audit_service(
            db_path=Path(tmp_dir) / "audit.db"
        )
        await service.start()
        
        # Log a realistic decision
        subject = SubjectDetails(
            type="user",
            id="emp-456",
            email="alice@example.com",
            roles=["developer", "team-lead"],
            teams=["platform"],
            clearance_level=3
        )
        
        resource = ResourceDetails(
            type="tool",
            id="db-admin-panel",
            server="production",
            classification=4
        )
        
        context = ContextDetails(
            ip_address="203.0.113.42",
            user_agent="web-browser/1.0",
            mfa_verified=True,
            time_of_day="14:30"
        )
        
        policies = [
            PolicyMatchDetails(
                id="mac-clearance-check",
                name="Clearance Level Policy",
                engine="mac",
                result="deny",
                explanation="User clearance (3) < Resource classification (4)"
            )
        ]
        
        # Log the decision
        await service.log_decision(
            decision=DecisionResult.DENY,
            action="tools.invoke",
            subject=subject,
            resource=resource,
            reason="Insufficient clearance level",
            matching_policies=policies,
            context=context,
            request_id="req-xyz-789",
            gateway_node="gateway-prod-1",
            duration_ms=4.2
        )
        
        # Query by email
        filter = AuditQueryFilter(subject_email="alice@example.com")
        results = await service.get_db_pool().query_decisions(filter)
        
        assert len(results) == 1
        result = results[0]
        assert result.decision == DecisionResult.DENY
        assert result.subject.clearance_level == 3
        assert result.resource.classification == 4
        assert result.context.mfa_verified is True
        assert len(result.matching_policies) == 1
        
        # Query denials
        filter = AuditQueryFilter(decision=DecisionResult.DENY)
        denials = await service.get_db_pool().query_decisions(filter)
        assert len(denials) == 1
        
        # Get statistics
        stats = await service.get_db_pool().get_statistics()
        assert stats.total_decisions == 1
        assert stats.denied == 1
        assert stats.allowed == 0
        
        await service.stop()


# =============================================================================
# Main
# =============================================================================

async def main():
    success = await runner.run()
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
