# -*- coding: utf-8 -*-
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
            resource=Resource(type="tool", id="any-tool")
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
            resource=Resource(type="tool", id="db-query")
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
            resource=Resource(type="tool", id="db-query")
        )
        assert decision.allowed is False

    @pytest.mark.asyncio
    async def test_owner_access(self, policy_engine):
        """Test that resource owners have full access."""
        subject = Subject(email="owner@example.com", is_admin=False, permissions=[])
        resource = Resource(
            type="tool",
            id="my-tool",
            owner="owner@example.com"
        )

        decision = await policy_engine.check_access(
            subject=subject,
            permission="tools.read",
            resource=resource
        )

        assert decision.allowed is True
        assert "owner" in decision.reason.lower()


class TestRequirePermissionV2Decorator:
    """Test the require_permission_v2 decorator."""

    @pytest.fixture
    def mock_db(self):
        """Mock database session."""
        from unittest.mock import MagicMock
        return MagicMock()

    @pytest.mark.asyncio
    async def test_decorator_with_admin_user(self, mock_db):
        """Test decorator allows admin users."""
        from mcpgateway.services.policy_engine import require_permission_v2

        @require_permission_v2("tools.delete")
        async def test_endpoint(user=None, db=None):
            return "success"

        user = {
            "email": "admin@example.com",
            "is_admin": True,
            "roles": ["admin"],
            "teams": [],
            "permissions": []
        }

        result = await test_endpoint(user=user, db=mock_db)
        assert result == "success"

    @pytest.mark.asyncio
    async def test_decorator_with_permission(self, mock_db):
        """Test decorator allows users with permission."""
        from mcpgateway.services.policy_engine import require_permission_v2

        @require_permission_v2("tools.read")
        async def test_endpoint(user=None, db=None):
            return "success"

        user = {
            "email": "user@example.com",
            "is_admin": False,
            "roles": ["developer"],
            "teams": [],
            "permissions": ["tools.read"]
        }

        result = await test_endpoint(user=user, db=mock_db)
        assert result == "success"

    @pytest.mark.asyncio
    async def test_decorator_denies_without_permission(self, mock_db):
        """Test decorator denies users without permission."""
        from mcpgateway.services.policy_engine import require_permission_v2
        from fastapi import HTTPException

        @require_permission_v2("tools.delete")
        async def test_endpoint(user=None, db=None):
            return "success"

        user = {
            "email": "user@example.com",
            "is_admin": False,
            "roles": [],
            "teams": [],
            "permissions": ["tools.read"]
        }

        with pytest.raises(HTTPException) as exc_info:
            await test_endpoint(user=user, db=mock_db)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_decorator_requires_user(self, mock_db):
        """Test decorator requires user parameter."""
        from mcpgateway.services.policy_engine import require_permission_v2
        from fastapi import HTTPException

        @require_permission_v2("tools.read")
        async def test_endpoint(db=None):
            return "success"

        with pytest.raises(HTTPException) as exc_info:
            await test_endpoint(db=mock_db)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_decorator_requires_db(self):
        """Test decorator requires db parameter."""
        from mcpgateway.services.policy_engine import require_permission_v2
        from fastapi import HTTPException

        @require_permission_v2("tools.read")
        async def test_endpoint(user=None):
            return "success"

        user = {"email": "test@example.com", "is_admin": True}

        with pytest.raises(HTTPException) as exc_info:
            await test_endpoint(user=user)

        assert exc_info.value.status_code == 500


class TestAccessDecision:
    """Test AccessDecision model."""

    def test_decision_creation(self):
        """Test creating an access decision."""
        from mcpgateway.services.policy_engine import AccessDecision

        decision = AccessDecision(
            allowed=True,
            reason="Test reason",
            permission="tools.read",
            subject_email="test@example.com",
            resource_type="tool",
            resource_id="tool-123",
            matching_policies=["policy-1", "policy-2"]
        )

        assert decision.allowed is True
        assert decision.reason == "Test reason"
        assert decision.permission == "tools.read"
        assert decision.subject_email == "test@example.com"
        assert decision.resource_type == "tool"
        assert decision.resource_id == "tool-123"
        assert len(decision.matching_policies) == 2
        assert decision.decision_id is not None
        assert decision.timestamp is not None


class TestContext:
    """Test Context model."""

    def test_context_creation(self):
        """Test creating a context."""
        from mcpgateway.services.policy_engine import Context

        context = Context(
            ip_address="192.168.1.1",
            user_agent="TestAgent/1.0",
            request_id="req-123"
        )

        assert context.ip_address == "192.168.1.1"
        assert context.user_agent == "TestAgent/1.0"
        assert context.request_id == "req-123"
        assert context.timestamp is not None


class TestPolicyEngineEdgeCases:
    """Test PolicyEngine edge cases."""

    @pytest.fixture
    def db_session(self):
        """Get database session."""
        db = next(get_db())
        yield db
        db.close()

    @pytest.fixture
    def policy_engine(self, db_session):
        """Create PolicyEngine instance."""
        return PolicyEngine(db_session)

    @pytest.mark.asyncio
    async def test_wildcard_permission(self, policy_engine):
        """Test wildcard permission grants all access."""
        subject = Subject(
            email="superuser@example.com",
            is_admin=False,
            permissions=["*"]
        )

        decision = await policy_engine.check_access(
            subject=subject,
            permission="any.permission",
            resource=Resource(type="anything")
        )

        assert decision.allowed is True

    @pytest.mark.asyncio
    async def test_team_member_non_team_resource(self, policy_engine):
        """Test team member cannot access non-team resource."""
        subject = Subject(
            email="member@example.com",
            is_admin=False,
            teams=["team-1"],
            permissions=[]
        )

        resource = Resource(
            type="tool",
            id="tool-123",
            team_id="team-2",
            visibility="team"
        )

        decision = await policy_engine.check_access(
            subject=subject,
            permission="tools.read",
            resource=resource
        )

        assert decision.allowed is False

    @pytest.mark.asyncio
    async def test_public_resource_non_read(self, policy_engine):
        """Test public resource with non-read permission."""
        subject = Subject(
            email="anyone@example.com",
            is_admin=False,
            permissions=[]
        )

        resource = Resource(
            type="tool",
            visibility="public"
        )

        decision = await policy_engine.check_access(
            subject=subject,
            permission="tools.delete",
            resource=resource
        )

        assert decision.allowed is False

    @pytest.mark.asyncio
    async def test_private_resource(self, policy_engine):
        """Test private resource access denied."""
        subject = Subject(
            email="someone@example.com",
            is_admin=False,
            permissions=[],
            teams=[]
        )

        resource = Resource(
            type="tool",
            id="private-tool",
            owner="owner@example.com",
            visibility="private"
        )

        decision = await policy_engine.check_access(
            subject=subject,
            permission="tools.read",
            resource=resource
        )

        assert decision.allowed is False


class TestWildcardPermissions:
    """Test wildcard permission matching logic."""
    
    def test_exact_match(self):
        """Test exact permission match."""
        from mcpgateway.services.policy_engine import PolicyEngine
        
        assert PolicyEngine._has_permission(["admin.system_config"], "admin.system_config") is True
        assert PolicyEngine._has_permission(["tools.read"], "admin.system_config") is False
    
    def test_wildcard_star_matches_all(self):
        """Test that * matches everything."""
        from mcpgateway.services.policy_engine import PolicyEngine
        
        assert PolicyEngine._has_permission(["*"], "admin.system_config") is True
        assert PolicyEngine._has_permission(["*"], "tools.read") is True
        assert PolicyEngine._has_permission(["*"], "anything.anything") is True
    
    def test_namespace_wildcard(self):
        """Test namespace.* matches namespace.anything."""
        from mcpgateway.services.policy_engine import PolicyEngine
        
        assert PolicyEngine._has_permission(["admin.*"], "admin.system_config") is True
        assert PolicyEngine._has_permission(["admin.*"], "admin.user_management") is True
        assert PolicyEngine._has_permission(["tools.*"], "tools.read") is True
        assert PolicyEngine._has_permission(["admin.*"], "tools.read") is False
    
    def test_wildcard_does_not_match_namespace_only(self):
        """Test admin.* does NOT match just 'admin'."""
        from mcpgateway.services.policy_engine import PolicyEngine
        
        # This should NOT match - admin.* requires admin.SOMETHING
        assert PolicyEngine._has_permission(["admin.*"], "admin") is False
    
    def test_multiple_permissions(self):
        """Test matching against multiple permissions."""
        from mcpgateway.services.policy_engine import PolicyEngine
        
        permissions = ["tools.read", "admin.system_config", "teams.*"]
        
        assert PolicyEngine._has_permission(permissions, "tools.read") is True
        assert PolicyEngine._has_permission(permissions, "admin.system_config") is True
        assert PolicyEngine._has_permission(permissions, "teams.create") is True
        assert PolicyEngine._has_permission(permissions, "teams.delete") is True
        assert PolicyEngine._has_permission(permissions, "servers.read") is False
