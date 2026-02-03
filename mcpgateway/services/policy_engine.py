"""
Centralized Policy Decision Point (PDP) for all access control decisions.

This replaces the scattered auth logic across middleware, decorators, and services
with a single, configurable policy engine.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from mcpgateway.db import Permissions

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Models (will move to separate file later)
# ---------------------------------------------------------------------------


class Subject:
    """Represents the entity requesting access (user, service, token)."""
    
    def __init__(
        self,
        email: str,
        roles: List[str] = None,
        teams: List[str] = None,
        is_admin: bool = False,
        permissions: List[str] = None,
        attributes: Dict[str, Any] = None
    ):
        self.email = email
        self.roles = roles or []
        self.teams = teams or []
        self.is_admin = is_admin
        self.permissions = permissions or []
        self.attributes = attributes or {}


class Resource:
    """Represents the thing being accessed."""
    
    def __init__(
        self,
        resource_type: str,
        resource_id: Optional[str] = None,
        owner: Optional[str] = None,
        team_id: Optional[str] = None,
        visibility: Optional[str] = None,
        attributes: Dict[str, Any] = None
    ):
        self.type = resource_type
        self.id = resource_id
        self.owner = owner
        self.team_id = team_id
        self.visibility = visibility
        self.attributes = attributes or {}


class Context:
    """Ambient request context."""
    
    def __init__(
        self,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_id: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        attributes: Dict[str, Any] = None
    ):
        self.ip_address = ip_address
        self.user_agent = user_agent
        self.request_id = request_id
        self.timestamp = timestamp or datetime.now(timezone.utc)
        self.attributes = attributes or {}


class AccessDecision:
    """Result of an access control decision."""
    
    def __init__(
        self,
        allowed: bool,
        reason: str,
        permission: str,
        subject_email: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        matching_policies: List[str] = None,
        decision_id: Optional[str] = None
    ):
        self.allowed = allowed
        self.reason = reason
        self.permission = permission
        self.subject_email = subject_email
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.matching_policies = matching_policies or []
        self.decision_id = decision_id or str(uuid4())
        self.timestamp = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Policy Engine
# ---------------------------------------------------------------------------


class PolicyEngine:
    """
    Centralized access control decision point.
    
    This is the single entry point for ALL authorization decisions in the gateway.
    It replaces:
    - @require_permission decorators
    - is_admin checks
    - Visibility filters
    - Token scoping middleware
    """
    
    def __init__(self, db: Session):
        """
        Initialize the policy engine.
        
        Args:
            db: Database session for querying policies and logging decisions
        """
        self.db = db
        logger.info("PolicyEngine initialized")
    
    async def check_access(
        self,
        subject: Subject,
        permission: str,
        resource: Optional[Resource] = None,
        context: Optional[Context] = None
    ) -> AccessDecision:
        """
        Check if subject has permission to perform action on resource.
        
        This is the MAIN method that replaces all auth checks.
        
        Args:
            subject: Who is requesting access
            permission: What permission they need (e.g., "tools.read")
            resource: Optional resource being accessed
            context: Optional request context
            
        Returns:
            AccessDecision with allowed=True/False and reason
            
        Examples:
            # Replace old decorator:
            # @require_permission("tools.read")
            # async def get_tool(tool_id, user):
            
            # With new check:
            decision = await policy_engine.check_access(
                subject=Subject(email=user.email, permissions=user.permissions, is_admin=user.is_admin),
                permission="tools.read",
                resource=Resource(resource_type="tool", resource_id=tool_id)
            )
            if not decision.allowed:
                raise HTTPException(403, detail=decision.reason)
        """
        context = context or Context()
        
        logger.debug(
            f"PolicyEngine.check_access: subject={subject.email}, "
            f"permission={permission}, resource={resource.type if resource else None}"
        )
        
        # Step 1: Admin bypass (admins have all permissions)
        if subject.is_admin:
            decision = AccessDecision(
                allowed=True,
                reason="Admin bypass: user has admin privileges",
                permission=permission,
                subject_email=subject.email,
                resource_type=resource.type if resource else None,
                resource_id=resource.id if resource else None,
                matching_policies=["admin-bypass"]
            )
            await self._log_decision(decision)
            return decision
        
        # Step 2: Check if subject has the specific permission
        if permission in subject.permissions or Permissions.ALL_PERMISSIONS in subject.permissions:
            decision = AccessDecision(
                allowed=True,
                reason=f"User has required permission: {permission}",
                permission=permission,
                subject_email=subject.email,
                resource_type=resource.type if resource else None,
                resource_id=resource.id if resource else None,
                matching_policies=["direct-permission"]
            )
            await self._log_decision(decision)
            return decision
        
        # Step 3: Check resource-level access (owner, team, visibility)
        if resource:
            resource_decision = await self._check_resource_access(subject, permission, resource)
            if resource_decision.allowed:
                await self._log_decision(resource_decision)
                return resource_decision
        
        # Step 4: Deny by default
        decision = AccessDecision(
            allowed=False,
            reason=f"Permission denied: user lacks '{permission}' permission",
            permission=permission,
            subject_email=subject.email,
            resource_type=resource.type if resource else None,
            resource_id=resource.id if resource else None,
            matching_policies=[]
        )
        await self._log_decision(decision)
        return decision
    
    async def _check_resource_access(
        self,
        subject: Subject,
        permission: str,
        resource: Resource
    ) -> AccessDecision:
        """
        Check resource-level access (owner, team membership, visibility).
        
        This replaces the visibility filtering logic in services.
        """
        # Owner always has access
        if resource.owner == subject.email:
            return AccessDecision(
                allowed=True,
                reason="Resource owner has full access",
                permission=permission,
                subject_email=subject.email,
                resource_type=resource.type,
                resource_id=resource.id,
                matching_policies=["owner-access"]
            )
        
        # Team members can access team resources
        if resource.team_id and resource.team_id in subject.teams:
            if resource.visibility == "team":
                return AccessDecision(
                    allowed=True,
                    reason=f"Team member access: user in team {resource.team_id}",
                    permission=permission,
                    subject_email=subject.email,
                    resource_type=resource.type,
                    resource_id=resource.id,
                    matching_policies=["team-access"]
                )
        
        # Public resources are accessible to everyone (if they have the base permission)
        if resource.visibility == "public":
            # For public resources, we still need a read permission at minimum
            if permission.endswith(".read"):
                return AccessDecision(
                    allowed=True,
                    reason="Public resource with read permission",
                    permission=permission,
                    subject_email=subject.email,
                    resource_type=resource.type,
                    resource_id=resource.id,
                    matching_policies=["public-access"]
                )
        
        # Deny by default
        return AccessDecision(
            allowed=False,
            reason="No resource-level access granted",
            permission=permission,
            subject_email=subject.email,
            resource_type=resource.type,
            resource_id=resource.id,
            matching_policies=[]
        )
    
    async def _log_decision(self, decision: AccessDecision) -> None:
        """
        Log the access decision to the audit trail.
        
        NOTE: This will write to access_decisions table once we create it.
        For now, just log to console.
        """
        logger.info(
            f"Access Decision [{decision.decision_id}]: "
            f"subject={decision.subject_email}, "
            f"permission={decision.permission}, "
            f"resource={decision.resource_type}:{decision.resource_id}, "
            f"allowed={decision.allowed}, "
            f"reason={decision.reason}"
        )
        # TODO: Write to access_decisions table


# ---------------------------------------------------------------------------
# New Decorator (uses PolicyEngine instead of old RBAC)
# ---------------------------------------------------------------------------


def require_permission_v2(permission: str, resource_type: Optional[str] = None):
    """
    New decorator using PolicyEngine (Phase 1 - #2019).
    
    This will eventually replace the old @require_permission decorator.
    For now, it coexists with the old system via feature flag.
    
    Args:
        permission: Required permission (e.g., 'servers.read')
        resource_type: Optional resource type
        
    Usage:
        @require_permission_v2("servers.read")
        async def list_servers(...):
            ...
    """
    from functools import wraps
    from fastapi import HTTPException
    
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract user from kwargs (passed by Depends(get_current_user))
            user = kwargs.get('user')
            db = kwargs.get('db')
            
            if not user:
                raise HTTPException(status_code=401, detail="Authentication required")
            
            if not db:
                raise HTTPException(status_code=500, detail="Database session not available")
            
            # Create PolicyEngine
            policy_engine = PolicyEngine(db)
            
            # Build Subject from user
            subject = Subject(
                email=user.get("email", "unknown"),
                roles=user.get("roles", []),
                teams=user.get("teams", []),
                is_admin=user.get("is_admin", False),
                permissions=user.get("permissions", [])
            )
            
            # Build Resource (basic - can be enhanced)
            resource = Resource(
                resource_type=resource_type or permission.split(".")[0],
                resource_id=None  # Not known at decorator time
            ) if resource_type else None
            
            # Check access
            decision = await policy_engine.check_access(
                subject=subject,
                permission=permission,
                resource=resource
            )
            
            if not decision.allowed:
                raise HTTPException(
                    status_code=403,
                    detail=f"Access denied: {decision.reason}"
                )
            
            # Access granted - call original function
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator
