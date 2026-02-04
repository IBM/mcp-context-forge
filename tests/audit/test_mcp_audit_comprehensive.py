"""
Comprehensive pytest test suite for IBM MCP Context Forge audit system.

Run with:
    pytest test_mcp_audit_comprehensive.py -v
    pytest test_mcp_audit_comprehensive.py -v --cov=. --cov-report=html
"""

import pytest
import asyncio
import tempfile
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

from mcp_audit_models import (
    AuditDecisionRecord,
    SubjectDetails,
    ResourceDetails,
    ContextDetails,
    PolicyMatchDetails,
    DecisionResult,
    AuditQueryFilter,
    AuditConfig,
    SIEMConfig,
    AuditStorageConfig,
    PolicyEngineType
)
from mcp_audit_database import SQLiteAuditDatabase, AuditDatabasePool
from mcp_audit_service import AuditService, create_audit_service


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def temp_db_path(tmp_path):
    """Provide a temporary database path."""
    return tmp_path / "test_audit.db"


@pytest.fixture
async def audit_database(temp_db_path):
    """Provide an initialized audit database."""
    db = SQLiteAuditDatabase(temp_db_path)
    await db.initialize()
    yield db
    await db.close()


@pytest.fixture
async def audit_service(temp_db_path):
    """Provide an initialized audit service."""
    service = create_audit_service(db_path=temp_db_path)
    await service.start()
    yield service
    await service.stop()


@pytest.fixture
def sample_subject():
    """Provide a sample subject."""
    return SubjectDetails(
        type="user",
        id="user-123",
        email="test.user@example.com",
        roles=["developer", "admin"],
        teams=["platform", "security"],
        clearance_level=3
    )


@pytest.fixture
def sample_resource():
    """Provide a sample resource."""
    return ResourceDetails(
        type="database",
        id="prod-customer-db",
        server="db-prod-01",
        classification=4,
        owner="data-team"
    )


@pytest.fixture
def sample_context():
    """Provide a sample context."""
    return ContextDetails(
        ip_address="192.168.1.100",
        user_agent="claude-desktop/1.0",
        mfa_verified=True,
        time_of_day="14:30",
        geo_location={"country": "US", "city": "San Francisco"}
    )


@pytest.fixture
def sample_policies():
    """Provide sample policy evaluations."""
    return [
        PolicyMatchDetails(
            id="mac-policy-1",
            name="Mandatory Access Control",
            engine="mac",
            result="deny",
            explanation="User clearance (3) < Resource classification (4)",
            evaluation_time_ms=2.5
        )
    ]


# =============================================================================
# Model Tests
# =============================================================================

class TestAuditModels:
    """Test audit data models."""
    
    def test_subject_details_creation(self, sample_subject):
        """Test creating SubjectDetails."""
        assert sample_subject.id == "user-123"
        assert sample_subject.email == "test.user@example.com"
        assert len(sample_subject.roles) == 2
        assert sample_subject.clearance_level == 3
    
    def test_subject_to_dict(self, sample_subject):
        """Test SubjectDetails serialization."""
        data = sample_subject.to_dict()
        assert data['id'] == "user-123"
        assert data['email'] == "test.user@example.com"
        assert 'developer' in data['roles']
    
    def test_resource_details_creation(self, sample_resource):
        """Test creating ResourceDetails."""
        assert sample_resource.id == "prod-customer-db"
        assert sample_resource.server == "db-prod-01"
        assert sample_resource.classification == 4
    
    def test_context_details_creation(self, sample_context):
        """Test creating ContextDetails."""
        assert sample_context.ip_address == "192.168.1.100"
        assert sample_context.mfa_verified is True
        assert sample_context.geo_location['country'] == "US"
    
    def test_policy_match_details(self, sample_policies):
        """Test PolicyMatchDetails."""
        policy = sample_policies[0]
        assert policy.id == "mac-policy-1"
        assert policy.result == "deny"
        assert policy.evaluation_time_ms == 2.5
    
    def test_audit_decision_record_creation(
        self, sample_subject, sample_resource, sample_context, sample_policies
    ):
        """Test creating complete AuditDecisionRecord."""
        record = AuditDecisionRecord(
            request_id="req-123",
            gateway_node="gw-1",
            subject=sample_subject,
            action="database.query",
            resource=sample_resource,
            decision=DecisionResult.DENY,
            reason="Insufficient clearance",
            matching_policies=sample_policies,
            context=sample_context,
            duration_ms=5.2
        )
        
        assert record.id is not None
        assert record.id.startswith("decision-")
        assert record.request_id == "req-123"
        assert record.decision == DecisionResult.DENY
        assert record.duration_ms == 5.2
    
    def test_record_to_dict_matches_schema(
        self, sample_subject, sample_resource, sample_context, sample_policies
    ):
        """Test record dict matches GitHub issue schema."""
        record = AuditDecisionRecord(
            request_id="req-12345",
            gateway_node="gateway-1",
            subject=sample_subject,
            action="tools.invoke",
            resource=sample_resource,
            decision=DecisionResult.DENY,
            reason="Insufficient clearance level",
            matching_policies=sample_policies,
            context=sample_context,
            duration_ms=5.0
        )
        
        data = record.to_dict()
        
        # Verify schema structure
        assert 'id' in data
        assert 'timestamp' in data
        assert 'request_id' in data
        assert data['request_id'] == "req-12345"
        assert 'gateway_node' in data
        assert data['gateway_node'] == "gateway-1"
        assert 'subject' in data
        assert data['subject']['email'] == "test.user@example.com"
        assert 'action' in data
        assert data['action'] == "tools.invoke"
        assert 'resource' in data
        assert data['resource']['id'] == "prod-customer-db"
        assert 'decision' in data
        assert data['decision'] == "deny"
        assert 'reason' in data
        assert 'matching_policies' in data
        assert len(data['matching_policies']) == 1
        assert 'context' in data
        assert data['context']['ip_address'] == "192.168.1.100"
        assert 'duration_ms' in data
        assert data['duration_ms'] == 5.0
    
    def test_record_to_json(self, sample_subject, sample_resource):
        """Test JSON serialization."""
        record = AuditDecisionRecord(
            subject=sample_subject,
            action="test",
            resource=sample_resource,
            decision=DecisionResult.ALLOW,
            reason="test"
        )
        
        json_str = record.to_json()
        parsed = json.loads(json_str)
        
        assert parsed['decision'] == 'allow'
        assert parsed['subject']['email'] == "test.user@example.com"
    
    def test_splunk_hec_format(self, sample_subject, sample_resource):
        """Test Splunk HTTP Event Collector format."""
        record = AuditDecisionRecord(
            gateway_node="gateway-prod-1",
            subject=sample_subject,
            action="test",
            resource=sample_resource,
            decision=DecisionResult.ALLOW
        )
        
        hec_data = record.to_splunk_hec()
        
        assert 'time' in hec_data
        assert isinstance(hec_data['time'], int)
        assert hec_data['host'] == "gateway-prod-1"
        assert hec_data['source'] == "mcp-policy-engine"
        assert hec_data['sourcetype'] == "policy_decision"
        assert 'event' in hec_data
        assert hec_data['event']['decision'] == 'allow'
    
    def test_elasticsearch_format(self, sample_subject, sample_resource):
        """Test Elasticsearch document format."""
        record = AuditDecisionRecord(
            subject=sample_subject,
            action="test",
            resource=sample_resource,
            decision=DecisionResult.DENY
        )
        
        es_doc = record.to_elasticsearch()
        
        assert '@timestamp' in es_doc
        assert es_doc['event_type'] == 'policy_decision'
        assert es_doc['decision'] == 'deny'
        assert 'subject' in es_doc
    
    def test_webhook_format(self, sample_subject, sample_resource):
        """Test generic webhook format."""
        record = AuditDecisionRecord(
            subject=sample_subject,
            action="test",
            resource=sample_resource,
            decision=DecisionResult.ALLOW
        )
        
        webhook_data = record.to_webhook()
        
        assert webhook_data['event_type'] == 'policy.decision'
        assert 'timestamp' in webhook_data
        assert 'data' in webhook_data
        assert webhook_data['data']['decision'] == 'allow'


class TestAuditQueryFilter:
    """Test query filter functionality."""
    
    def test_basic_filter_creation(self):
        """Test creating a basic query filter."""
        filter = AuditQueryFilter(
            subject_email="user@example.com",
            decision=DecisionResult.DENY,
            limit=50
        )
        
        assert filter.subject_email == "user@example.com"
        assert filter.decision == DecisionResult.DENY
        assert filter.limit == 50
    
    def test_time_range_filter(self):
        """Test time range filtering."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=7)
        
        filter = AuditQueryFilter(
            start_time=start,
            end_time=now
        )
        
        assert filter.start_time == start
        assert filter.end_time == now
    
    def test_multiple_filters(self):
        """Test combining multiple filters."""
        filter = AuditQueryFilter(
            subject_id="user-123",
            resource_type="database",
            action="query",
            decision=DecisionResult.DENY,
            limit=100
        )
        
        assert filter.subject_id == "user-123"
        assert filter.resource_type == "database"
        assert filter.action == "query"


class TestAuditConfig:
    """Test configuration models."""
    
    def test_default_config(self):
        """Test default configuration."""
        config = AuditConfig()
        
        assert config.decisions_enabled is True
        assert config.log_allowed is True
        assert config.log_denied is True
        assert config.include_context is True
    
    def test_storage_config(self):
        """Test storage configuration."""
        storage = AuditStorageConfig(
            type="database",
            retention_days=365,
            partition_by="month"
        )
        
        assert storage.type == "database"
        assert storage.retention_days == 365
        assert storage.partition_by == "month"
    
    def test_siem_config(self):
        """Test SIEM configuration."""
        siem = SIEMConfig(
            enabled=True,
            type="splunk",
            endpoint="https://splunk.example.com:8088",
            batch_size=100
        )
        
        assert siem.enabled is True
        assert siem.type == "splunk"
        assert siem.batch_size == 100
    
    def test_config_to_dict(self):
        """Test configuration serialization."""
        config = AuditConfig(
            decisions_enabled=True,
            storage=AuditStorageConfig(retention_days=90)
        )
        
        data = config.to_dict()
        
        assert data['decisions']['enabled'] is True
        assert data['storage']['retention_days'] == 90


# =============================================================================
# Database Tests
# =============================================================================

class TestAuditDatabase:
    """Test database operations."""
    
    @pytest.mark.asyncio
    async def test_database_initialization(self, temp_db_path):
        """Test database schema creation."""
        db = SQLiteAuditDatabase(temp_db_path)
        await db.initialize()
        
        # Check that table exists
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_decisions'"
        )
        result = cursor.fetchone()
        assert result is not None
        
        await db.close()
    
    @pytest.mark.asyncio
    async def test_store_decision(
        self, audit_database, sample_subject, sample_resource
    ):
        """Test storing a decision record."""
        record = AuditDecisionRecord(
            subject=sample_subject,
            action="test.action",
            resource=sample_resource,
            decision=DecisionResult.ALLOW,
            reason="Test reason"
        )
        
        await audit_database.store_decision(record)
        
        # Verify stored
        cursor = audit_database.conn.execute(
            "SELECT COUNT(*) FROM audit_decisions"
        )
        count = cursor.fetchone()[0]
        assert count == 1
    
    @pytest.mark.asyncio
    async def test_store_multiple_decisions(
        self, audit_database, sample_subject, sample_resource
    ):
        """Test storing multiple decisions."""
        for i in range(5):
            record = AuditDecisionRecord(
                subject=sample_subject,
                action=f"action_{i}",
                resource=sample_resource,
                decision=DecisionResult.ALLOW,
                reason=f"Test {i}"
            )
            await audit_database.store_decision(record)
        
        cursor = audit_database.conn.execute(
            "SELECT COUNT(*) FROM audit_decisions"
        )
        count = cursor.fetchone()[0]
        assert count == 5
    
    @pytest.mark.asyncio
    async def test_query_all_decisions(self, audit_database, sample_subject, sample_resource):
        """Test querying all decisions."""
        # Store test data
        for i in range(3):
            record = AuditDecisionRecord(
                subject=sample_subject,
                action=f"action_{i}",
                resource=sample_resource,
                decision=DecisionResult.ALLOW,
                reason="test"
            )
            await audit_database.store_decision(record)
        
        # Query all
        filter = AuditQueryFilter(limit=10)
        results = await audit_database.query_decisions(filter)
        
        assert len(results) == 3
    
    @pytest.mark.asyncio
    async def test_query_by_subject_id(self, audit_database, sample_resource):
        """Test querying by subject ID."""
        # Store decisions for different subjects
        for i in range(5):
            subject = SubjectDetails(
                type="user",
                id=f"user-{i % 2}",  # Alternating user-0 and user-1
                email=f"user{i % 2}@example.com"
            )
            record = AuditDecisionRecord(
                subject=subject,
                action="test",
                resource=sample_resource,
                decision=DecisionResult.ALLOW,
                reason="test"
            )
            await audit_database.store_decision(record)
        
        # Query for user-0
        filter = AuditQueryFilter(subject_id="user-0")
        results = await audit_database.query_decisions(filter)
        
        assert len(results) == 3  # indices 0, 2, 4
        assert all(r.subject.id == "user-0" for r in results)
    
    @pytest.mark.asyncio
    async def test_query_by_subject_email(self, audit_database, sample_resource):
        """Test querying by subject email."""
        subject = SubjectDetails(
            type="user",
            id="user-1",
            email="specific.user@example.com"
        )
        
        # Store one record with specific email
        record = AuditDecisionRecord(
            subject=subject,
            action="test",
            resource=sample_resource,
            decision=DecisionResult.ALLOW,
            reason="test"
        )
        await audit_database.store_decision(record)
        
        # Query by email
        filter = AuditQueryFilter(subject_email="specific.user@example.com")
        results = await audit_database.query_decisions(filter)
        
        assert len(results) == 1
        assert results[0].subject.email == "specific.user@example.com"
    
    @pytest.mark.asyncio
    async def test_query_by_decision_type(self, audit_database, sample_subject, sample_resource):
        """Test querying by decision (allow/deny)."""
        # Store mixed decisions
        for i in range(10):
            decision = DecisionResult.DENY if i % 3 == 0 else DecisionResult.ALLOW
            record = AuditDecisionRecord(
                subject=sample_subject,
                action="test",
                resource=sample_resource,
                decision=decision,
                reason="test"
            )
            await audit_database.store_decision(record)
        
        # Query denials
        filter = AuditQueryFilter(decision=DecisionResult.DENY)
        results = await audit_database.query_decisions(filter)
        
        assert len(results) == 4  # indices 0, 3, 6, 9
        assert all(r.decision == DecisionResult.DENY for r in results)
    
    @pytest.mark.asyncio
    async def test_query_by_time_range(self, audit_database, sample_subject, sample_resource):
        """Test querying by time range."""
        now = datetime.now(timezone.utc)
        
        # Store records at different times
        for i in range(5):
            record = AuditDecisionRecord(
                timestamp=now - timedelta(hours=i),
                subject=sample_subject,
                action="test",
                resource=sample_resource,
                decision=DecisionResult.ALLOW,
                reason="test"
            )
            await audit_database.store_decision(record)
        
        # Query last 2 hours
        filter = AuditQueryFilter(
            start_time=now - timedelta(hours=2),
            end_time=now
        )
        results = await audit_database.query_decisions(filter)
        
        # Should get records from 0, 1, 2 hours ago (3 total)
        assert len(results) == 3
    
    @pytest.mark.asyncio
    async def test_query_by_resource_type(self, audit_database, sample_subject):
        """Test querying by resource type."""
        # Store decisions for different resource types
        for i in range(6):
            resource = ResourceDetails(
                type="database" if i % 2 == 0 else "api",
                id=f"resource-{i}"
            )
            record = AuditDecisionRecord(
                subject=sample_subject,
                action="test",
                resource=resource,
                decision=DecisionResult.ALLOW,
                reason="test"
            )
            await audit_database.store_decision(record)
        
        # Query for database resources
        filter = AuditQueryFilter(resource_type="database")
        results = await audit_database.query_decisions(filter)
        
        assert len(results) == 3
        assert all(r.resource.type == "database" for r in results)
    
    @pytest.mark.asyncio
    async def test_query_pagination(self, audit_database, sample_subject, sample_resource):
        """Test query pagination."""
        # Store 20 records
        for i in range(20):
            record = AuditDecisionRecord(
                subject=sample_subject,
                action=f"action_{i}",
                resource=sample_resource,
                decision=DecisionResult.ALLOW,
                reason="test"
            )
            await audit_database.store_decision(record)
        
        # Get first page
        filter = AuditQueryFilter(limit=5, offset=0)
        page1 = await audit_database.query_decisions(filter)
        assert len(page1) == 5
        
        # Get second page
        filter = AuditQueryFilter(limit=5, offset=5)
        page2 = await audit_database.query_decisions(filter)
        assert len(page2) == 5
        
        # Verify different results
        assert page1[0].id != page2[0].id
    
    @pytest.mark.asyncio
    async def test_get_statistics(self, audit_database, sample_subject, sample_resource):
        """Test statistics calculation."""
        # Store varied records
        for i in range(20):
            decision = DecisionResult.ALLOW if i % 2 == 0 else DecisionResult.DENY
            subject = SubjectDetails(type="user", id=f"user-{i % 5}")
            resource = ResourceDetails(type="doc", id=f"doc-{i % 3}")
            
            record = AuditDecisionRecord(
                subject=subject,
                action="test",
                resource=resource,
                decision=decision,
                reason="test",
                duration_ms=float(i * 2)
            )
            await audit_database.store_decision(record)
        
        stats = await audit_database.get_statistics()
        
        assert stats.total_decisions == 20
        assert stats.allowed == 10
        assert stats.denied == 10
        assert stats.unique_subjects == 5
        assert stats.unique_resources == 3
        assert stats.avg_duration_ms > 0
    
    @pytest.mark.asyncio
    async def test_delete_old_records(self, audit_database, sample_subject, sample_resource):
        """Test deleting old records."""
        now = datetime.now(timezone.utc)
        
        # Store old and new records
        old_record = AuditDecisionRecord(
            timestamp=now - timedelta(days=400),
            subject=sample_subject,
            action="old",
            resource=sample_resource,
            decision=DecisionResult.ALLOW,
            reason="test"
        )
        await audit_database.store_decision(old_record)
        
        new_record = AuditDecisionRecord(
            timestamp=now,
            subject=sample_subject,
            action="new",
            resource=sample_resource,
            decision=DecisionResult.ALLOW,
            reason="test"
        )
        await audit_database.store_decision(new_record)
        
        # Delete records older than 365 days
        deleted_count = await audit_database.delete_old_records(365)
        
        assert deleted_count == 1
        
        # Verify only new record remains
        filter = AuditQueryFilter(limit=10)
        results = await audit_database.query_decisions(filter)
        assert len(results) == 1
        assert results[0].action == "new"


# =============================================================================
# Service Tests
# =============================================================================

class TestAuditService:
    """Test audit service functionality."""
    
    @pytest.mark.asyncio
    async def test_create_service(self, temp_db_path):
        """Test creating audit service."""
        service = create_audit_service(db_path=temp_db_path)
        await service.start()
        
        assert service is not None
        assert service.config.decisions_enabled is True
        
        await service.stop()
    
    @pytest.mark.asyncio
    async def test_log_allowed_decision(
        self, audit_service, sample_subject, sample_resource,
        sample_context, sample_policies
    ):
        """Test logging an allowed decision."""
        record = await audit_service.log_decision(
            decision=DecisionResult.ALLOW,
            action="database.read",
            subject=sample_subject,
            resource=sample_resource,
            reason="Access granted by RBAC",
            matching_policies=sample_policies,
            context=sample_context,
            request_id="req-001",
            gateway_node="gw-1",
            duration_ms=3.5
        )
        
        assert record is not None
        assert record.decision == DecisionResult.ALLOW
        assert record.request_id == "req-001"
        assert record.duration_ms == 3.5
    
    @pytest.mark.asyncio
    async def test_log_denied_decision(
        self, audit_service, sample_subject, sample_resource
    ):
        """Test logging a denied decision."""
        record = await audit_service.log_decision(
            decision=DecisionResult.DENY,
            action="database.write",
            subject=sample_subject,
            resource=sample_resource,
            reason="Insufficient clearance",
            request_id="req-002"
        )
        
        assert record is not None
        assert record.decision == DecisionResult.DENY
        assert "Insufficient clearance" in record.reason
    
    @pytest.mark.asyncio
    async def test_config_controls_logging(self, temp_db_path, sample_subject, sample_resource):
        """Test that configuration controls what gets logged."""
        # Create service that doesn't log allowed decisions
        config = AuditConfig(
            decisions_enabled=True,
            log_allowed=False,
            log_denied=True
        )
        service = AuditService(config, temp_db_path)
        await service.start()
        
        # Try to log allowed decision
        record = await service.log_decision(
            decision=DecisionResult.ALLOW,
            action="test",
            subject=sample_subject,
            resource=sample_resource,
            reason="test"
        )
        
        # Should not be logged
        assert record is None
        
        # Log denied decision
        record = await service.log_decision(
            decision=DecisionResult.DENY,
            action="test",
            subject=sample_subject,
            resource=sample_resource,
            reason="test"
        )
        
        # Should be logged
        assert record is not None
        
        await service.stop()
    
    @pytest.mark.asyncio
    async def test_query_via_service(self, audit_service, sample_subject, sample_resource):
        """Test querying decisions through service."""
        # Log multiple decisions
        for i in range(5):
            await audit_service.log_decision(
                decision=DecisionResult.ALLOW,
                action=f"action_{i}",
                subject=sample_subject,
                resource=sample_resource,
                reason="test"
            )
        
        # Query all
        filter = AuditQueryFilter(limit=10)
        results = await audit_service.get_db_pool().query_decisions(filter)
        
        assert len(results) == 5
    
    @pytest.mark.asyncio
    async def test_end_to_end_workflow(
        self, audit_service, sample_subject, sample_resource,
        sample_context, sample_policies
    ):
        """Test complete workflow from logging to querying."""
        # Log a decision
        await audit_service.log_decision(
            decision=DecisionResult.DENY,
            action="tools.invoke",
            subject=sample_subject,
            resource=sample_resource,
            reason="Insufficient clearance level",
            matching_policies=sample_policies,
            context=sample_context,
            request_id="req-xyz-789",
            gateway_node="gateway-prod-1",
            duration_ms=4.2
        )
        
        # Query by email
        filter = AuditQueryFilter(subject_email=sample_subject.email)
        results = await audit_service.get_db_pool().query_decisions(filter)
        
        assert len(results) == 1
        result = results[0]
        assert result.decision == DecisionResult.DENY
        assert result.subject.clearance_level == 3
        assert result.resource.classification == 4
        assert result.context.mfa_verified is True
        assert len(result.matching_policies) == 1
        assert result.request_id == "req-xyz-789"
        
        # Get statistics
        stats = await audit_service.get_db_pool().get_statistics()
        assert stats.total_decisions == 1
        assert stats.denied == 1
        assert stats.allowed == 0


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for complete workflows."""
    
    @pytest.mark.asyncio
    async def test_mac_policy_workflow(self, audit_service):
        """Test Mandatory Access Control policy workflow."""
        # Subject with clearance level 2
        subject = SubjectDetails(
            type="contractor",
            id="ext-999",
            email="contractor@partner.com",
            clearance_level=2
        )
        
        # Resource with classification 4
        resource = ResourceDetails(
            type="database",
            id="classified-db",
            classification=4
        )
        
        # MAC policy denies access
        policies = [
            PolicyMatchDetails(
                id="mac-clearance",
                name="Clearance Level Check",
                engine="mac",
                result="deny",
                explanation="User clearance (2) < Resource classification (4)"
            )
        ]
        
        # Log the denial
        await audit_service.log_decision(
            decision=DecisionResult.DENY,
            action="database.query",
            subject=subject,
            resource=resource,
            reason="Insufficient clearance",
            matching_policies=policies
        )
        
        # Query denials
        filter = AuditQueryFilter(decision=DecisionResult.DENY)
        denials = await audit_service.get_db_pool().query_decisions(filter)
        
        assert len(denials) == 1
        assert denials[0].subject.clearance_level < denials[0].resource.classification
    
    @pytest.mark.asyncio
    async def test_rbac_policy_workflow(self, audit_service):
        """Test Role-Based Access Control workflow."""
        # Developer accessing development tools
        developer = SubjectDetails(
            type="user",
            id="dev-123",
            email="developer@example.com",
            roles=["developer", "team-lead"]
        )
        
        resource = ResourceDetails(
            type="tool",
            id="code-review-tool"
        )
        
        policies = [
            PolicyMatchDetails(
                id="rbac-dev-tools",
                name="Developer Tools Access",
                engine="rbac",
                result="allow",
                explanation="User has developer role"
            )
        ]
        
        await audit_service.log_decision(
            decision=DecisionResult.ALLOW,
            action="tools.use",
            subject=developer,
            resource=resource,
            reason="RBAC policy allows",
            matching_policies=policies
        )
        
        # Query by role
        filter = AuditQueryFilter(subject_id="dev-123")
        results = await audit_service.get_db_pool().query_decisions(filter)
        
        assert len(results) == 1
        assert "developer" in results[0].subject.roles


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
