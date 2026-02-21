# -*- coding: utf-8 -*-
"""
Centralized Policy Decision Point (PDP) for all access control decisions.

This replaces the scattered auth logic across middleware, decorators, and services
with a single, configurable policy engine.
"""

# Standard
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
import logging
from typing import Any, Dict, List, Optional
from uuid import uuid4

# Third-Party
from fastapi import HTTPException
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Models (will move to separate file later)
# ---------------------------------------------------------------------------


@dataclass
class Subject:
    """Represents the entity requesting access (user, service, token)."""

    email: str
    roles: List[str] = field(default_factory=list)
    teams: List[str] = field(default_factory=list)
    is_admin: bool = False
    permissions: List[str] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Resource:
    """Represents the thing being accessed."""

    type: str  # renamed from resource_type
    id: Optional[str] = None  # renamed from resource_id
    owner: Optional[str] = None
    team_id: Optional[str] = None
    visibility: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Context:
    """Ambient request context."""

    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    request_id: Optional[str] = None
    timestamp: Optional[datetime] = None
    attributes: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Initialize default timestamp if not provided."""
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)


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
        decision_id: Optional[str] = None,
    ):
        """Initialize an AccessDecision.

        Args:
            allowed: Whether access is granted
            reason: Explanation for the decision
            permission: Permission being checked
            subject_email: Email of requesting subject
            resource_type: Type of resource accessed
            resource_id: ID of resource accessed
            matching_policies: List of policy IDs that matched
            decision_id: Unique decision identifier
        """
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

    @staticmethod
    def _has_permission(user_permissions: list, required: str) -> bool:
        """Check if user has the required permission, supporting wildcards.

        Args:
            user_permissions: List of permission strings (e.g., ["admin.*", "tools.read"])
            required: The permission to check (e.g., "admin.system_config")

        Returns:
            bool: True if permission is granted
        """
        for perm in user_permissions:
            if perm == required:
                return True
            if perm == "*":
                return True
            if perm.endswith(".*"):
                prefix = perm[:-2]  # "admin.*" -> "admin"
                if required.startswith(prefix + "."):
                    return True
        return False

    async def check_access(self, subject: Subject, permission: str, resource: Optional[Resource] = None, context: Optional[Context] = None, allow_admin_bypass: bool = True) -> AccessDecision:
        """
        Check if subject has permission to perform action on resource.

        This is the MAIN method that replaces all auth checks.

        Args:
            subject: Who is requesting access
            permission: What permission they need (e.g., "tools.read")
            resource: Optional resource being accessed
            context: Optional request context
            allow_admin_bypass: If False, admins must have explicit permission (default: True)

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
                resource=Resource(type="tool", id=tool_id)
            )
            if not decision.allowed:
                raise HTTPException(403, detail=decision.reason)
        """
        context = context or Context()

        logger.debug("PolicyEngine.check_access: subject=%s, permission=%s, resource=%s", subject.email, permission, resource.type if resource else None)

        # Step 1: Admin bypass (admins have all permissions, if allowed)
        if subject.is_admin and allow_admin_bypass:
            decision = AccessDecision(
                allowed=True,
                reason="Admin bypass: user has admin privileges",
                permission=permission,
                subject_email=subject.email,
                resource_type=resource.type if resource else None,
                resource_id=resource.id if resource else None,
                matching_policies=["admin-bypass"],
            )
            await self._log_decision(decision)
            return decision

        # Step 2: Check if subject has the specific permission
        if self._has_permission(subject.permissions, permission):
            decision = AccessDecision(
                allowed=True,
                reason=f"User has required permission: {permission}",
                permission=permission,
                subject_email=subject.email,
                resource_type=resource.type if resource else None,
                resource_id=resource.id if resource else None,
                matching_policies=["direct-permission"],
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
            matching_policies=[],
        )
        await self._log_decision(decision)
        return decision

    async def _check_resource_access(self, subject: Subject, permission: str, resource: Resource) -> AccessDecision:
        """
        Check resource-level access (owner, team membership, visibility).

        NOTE: This is Phase 2+ scaffolding. Currently not called because:
        - No decorator passes resource_type parameter
        - Resource is always None in check_access()
        - This method never executes

        Phase 2 Activation Plan:
        When decorators pass resource_type (e.g., @require_permission_v2("tools.read", resource_type="tool")):
        1. Decorator will extract resource_id from function parameters (tool_id, server_id, etc.)
        2. Create Resource object with type and id
        3. This method will check owner/team/visibility rules
        4. Enable fine-grained per-resource permissions

        Example future usage:
            @require_permission_v2("tools.read", resource_type="tool")
            async def get_tool(tool_id: str, ...):
                # Will check if user can access this specific tool
                # Based on ownership, team membership, or public visibility

        Args:
            subject: The subject requesting access
            permission: Required permission string
            resource: The resource being accessed

        Returns:
            AccessDecision: The access control decision

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
                matching_policies=["owner-access"],
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
                    matching_policies=["team-access"],
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
                    matching_policies=["public-access"],
                )

        # Deny by default
        return AccessDecision(
            allowed=False, reason="No resource-level access granted", permission=permission, subject_email=subject.email, resource_type=resource.type, resource_id=resource.id, matching_policies=[]
        )

    async def _log_decision(self, decision: AccessDecision) -> None:
        """
        Log the access decision to the audit trail.

        Args:
            decision: The access decision to log

        NOTE: Database audit logging will be implemented in Phase 2.
        For Phase 1, we log to application logs at DEBUG level.
        The AccessDecisionLog table is created and ready for Phase 2.
        """
        logger.debug(
            "Access Decision [%s]: subject=%s, permission=%s, resource=%s:%s, allowed=%s, reason=%s",
            decision.decision_id,
            decision.subject_email,
            decision.permission,
            decision.resource_type,
            decision.resource_id,
            decision.allowed,
            decision.reason,
        )


# ---------------------------------------------------------------------------
# New Decorator (uses PolicyEngine instead of old RBAC)
# ---------------------------------------------------------------------------


def require_permission_v2(permission: str, resource_type: Optional[str] = None, allow_admin_bypass: bool = True):
    """
    New decorator using PolicyEngine (Phase 1 - #2019).

    This will eventually replace the old @require_permission decorator.

    Args:
        permission: Required permission (e.g., 'servers.read')
        resource_type: Optional resource type
        allow_admin_bypass: If False, even admins must have explicit permission (default: True)

    Returns:
        Callable: Decorator that enforces permission checks

    Usage:
        @require_permission_v2("servers.read")
        async def list_servers(...):
            ...
    """

    def decorator(func):
        """Decorate function with permission enforcement.

        Args:
            func: The function to wrap

        Returns:
            Callable: The wrapped function
        """

        @wraps(func)
        async def wrapper(*args, **kwargs):
            """Enforce permission checks before calling wrapped function.

            Args:
                *args: Positional arguments passed to wrapped function
                **kwargs: Keyword arguments passed to wrapped function

            Returns:
                Any: Result of the wrapped function

            Raises:
                HTTPException: If authentication or authorization fails
            """
            # PolicyEngine is now always active (no skip flag)
            # Tests have proper permissions in fixtures

            # Extract user from kwargs (supports different parameter names)
            user = kwargs.get("user") or kwargs.get("_user") or kwargs.get("current_user_ctx") or kwargs.get("current_user")
            db = kwargs.get("db") or kwargs.get("_db") or (user.get("db") if isinstance(user, dict) else getattr(user, "db", None))

            if not user:
                raise HTTPException(status_code=401, detail="Authentication required")

            if not db:
                raise HTTPException(status_code=500, detail="Database session not available")

            # Create PolicyEngine (per-request instantiation)
            # NOTE: PolicyEngine is instantiated on every request. This is acceptable
            # for Phase 1 but could be optimized in Phase 2+ with caching/pooling.
            policy_engine = PolicyEngine(db)

            # Build Subject from user
            # Handle both dict and object-style user
            if isinstance(user, dict):
                email = user.get("email", "unknown")
                roles = user.get("roles", [])
                teams = user.get("teams", [])
                is_admin = user.get("is_admin", False)
                permissions = user.get("permissions", [])
            else:
                email = getattr(user, "email", "unknown")
                roles = getattr(user, "roles", [])
                teams = getattr(user, "teams", [])
                is_admin = getattr(user, "is_admin", False)
                permissions = getattr(user, "permissions", [])

            subject = Subject(email=email, roles=roles, teams=teams, is_admin=is_admin, permissions=permissions)

            # Build Resource (basic - can be enhanced)
            resource = Resource(type=resource_type or permission.split(".")[0], id=None) if resource_type else None  # Not known at decorator time

            # Check access (pass allow_admin_bypass to check_access)
            decision = await policy_engine.check_access(subject=subject, permission=permission, resource=resource, allow_admin_bypass=allow_admin_bypass)

            if not decision.allowed:
                raise HTTPException(status_code=403, detail=f"Access denied: {decision.reason}")

            # Access granted - call original function
            return await func(*args, **kwargs)

        return wrapper

    return decorator
