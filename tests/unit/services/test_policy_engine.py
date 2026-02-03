"""Unit tests for the PolicyEngine service (Phase 1 - #2019)"""

import pytest
from mcpgateway.services.policy_engine import (
    PolicyEngine, Subject, Resource, Context, AccessDecision
)
from mcpgateway.db import get_db


class TestSubject:
    """Test Subject data model."""
    
    def test_subject_creation(self):
        subject = Subject(
            email="test@example.com",
            roles=["developer"],
            teams=["engineering"],
            is_admin=False
        )
        assert subject.email == "test@example.com"
        assert "developer" in subject.roles


class TestPolicyEngine:
    """Test PolicyEngine access control logic."""
    
    @pytest.fixture
    def db_session(self):
        """Get database session for tests."""
        db = next(get_db())
        yield db
        db.close()
    
    @pytest.fixture
    def policy_engine(self, db_session):
        """Create PolicyEngine instance."""
        return PolicyEngine(db_session)
    
    @pytest.mark.asyncio
    async def test_admin_bypass(self, policy_engine):
        """Test that admins have all permissions."""
        subject = Subject(email="admin@example.com", is_admin=True, roles=["admin"])
        
        decision = await policy_engine.check_access(
            subject=subject,
            permission="tools.delete",
            resource=Resource(resource_type="tool", resource_id="any-tool")
        )
        
        assert decision.allowed is True
        assert "admin" in decision.reason.lower()
    
    @pytest.mark.asyncio
    async def test_permission_check_allow(self, policy_engine):
        """Test direct permission check - allowed."""
        subject = Subject(
            email="dev@example.com",
            is_admin=False,
            permissions=["tools.read"]
        )
        
        decision = await policy_engine.check_access(
            subject=subject,
            permission="tools.read",
            resource=Resource(resource_type="tool", resource_id="db-query")
        )
        assert decision.allowed is True
    
    @pytest.mark.asyncio
    async def test_permission_check_deny(self, policy_engine):
        """Test direct permission check - denied."""
        subject = Subject(
            email="dev@example.com",
            is_admin=False,
            permissions=["tools.read"]
        )
        
        decision = await policy_engine.check_access(
            subject=subject,
            permission="tools.delete",
            resource=Resource(resource_type="tool", resource_id="db-query")
        )
        assert decision.allowed is False
    
    @pytest.mark.asyncio
    async def test_owner_access(self, policy_engine):
        """Test that resource owners have full access."""
        subject = Subject(email="owner@example.com", is_admin=False, permissions=[])
        resource = Resource(
            resource_type="tool",
            resource_id="my-tool",
            owner="owner@example.com"
        )
        
        decision = await policy_engine.check_access(
            subject=subject,
            permission="tools.read",
            resource=resource
        )
        
        assert decision.allowed is True
        assert "owner" in decision.reason.lower()
