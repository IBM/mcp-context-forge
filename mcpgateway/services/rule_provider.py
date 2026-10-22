# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/rule_provider.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Layer-2 rule provider seam.

A rule provider answers Layer-2 (RBAC) authorization questions. The
factory :func:`get_rule_provider` selects the implementation from
``Settings.rbac_rule_provider``. Layer-1 token scope enforcement
(``token_scope_grants``) never passes through this seam.

Consumer modules import the factory under the historical name::

    from mcpgateway.services.rule_provider import get_rule_provider as PermissionService

This keeps every construction site and every test patch target stable
while routing construction through the flag-aware dispatch.
"""

from typing import List, Optional, Protocol, Set, runtime_checkable

from sqlalchemy.orm import Session

from mcpgateway.config import settings
from mcpgateway.services.permission_service import PermissionService


@runtime_checkable
class RuleProvider(Protocol):
    """Layer-2 authorization contract shared by every provider.

    Method signatures mirror :class:`~mcpgateway.services.permission_service.PermissionService`
    so the default provider needs no adaptation and alternate engines stay
    drop-in. All authorization methods are coroutines.
    """

    async def check_permission(
        self,
        user_email: str,
        permission: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        team_id: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        allow_admin_bypass: bool = True,
        check_any_team: bool = False,
        token_is_admin: bool = False,
        token_roles: Optional[List[str]] = None,
    ) -> bool:
        """Answer whether the principal holds the permission."""
        ...

    async def has_admin_permission(self, user_email: str, team_id: Optional[str] = None, token_teams: Optional[List[str]] = None) -> bool:
        """Answer whether the principal may use admin surfaces."""
        ...

    async def check_platform_admin_permission(self, user_email: str, token_teams: Optional[List[str]] = None) -> bool:
        """Answer whether the principal is an unrestricted platform admin."""
        ...

    async def get_user_permissions(
        self,
        user_email: str,
        team_id: Optional[str] = None,
        include_all_teams: bool = False,
        token_teams: Optional[List[str]] = None,
        token_roles: Optional[List[str]] = None,
    ) -> Set[str]:
        """Return the effective permission set for the principal."""
        ...

    async def has_permission_on_resource(self, user_email: str, permission: str, resource_type: str, resource_id: str, team_id: Optional[str] = None) -> bool:
        """Answer whether the principal holds the permission on one resource."""
        ...

    async def check_resource_ownership(self, user_email: str, resource, allow_team_admin: bool = True) -> bool:
        """Answer whether the principal owns the resource."""
        ...

    def invalidate_user(self, user_email: str) -> None:
        """Drop cached decisions for the principal after a role change."""
        ...


class DbRuleProvider(PermissionService):
    """Default provider: the database-backed role model plus rule catalog.

    Inherits every authorization method from
    :class:`~mcpgateway.services.permission_service.PermissionService`.
    ``check_permission`` additionally applies the ``rbac_rules`` catalog
    as an overlay: a matching deny rule blocks, a matching allow rule
    grants, and no matching rule leaves the decision unchanged. Platform
    admin bypass is evaluated before the overlay, so a bypass grant is
    never denied by a catalog rule.
    """

    async def check_permission(
        self,
        user_email: str,
        permission: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        team_id: Optional[str] = None,
        token_teams: Optional[List[str]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        allow_admin_bypass: bool = True,
        check_any_team: bool = False,
        token_is_admin: bool = False,
        token_roles: Optional[List[str]] = None,
        args: Optional[dict] = None,
    ) -> bool:
        """Answer the permission question with the catalog overlay applied.

        Args:
            user_email: Principal identity.
            permission: Permission string being checked.
            resource_type: Optional resource type of the target entity.
            resource_id: Optional entity id for entity-scoped rules.
            team_id: Optional team scope of the check.
            token_teams: Layer-1 narrowed team list, when present.
            ip_address: Caller address for audit rows.
            user_agent: Caller agent for audit rows.
            allow_admin_bypass: Whether platform admins bypass the check.
            check_any_team: Grant when the permission holds in any team.
            token_is_admin: Admin flag from the token, when present.
            token_roles: Role names from the token, when present.
            args: Tool arguments from Mcp-Param-* headers (SEP-2243).

        Returns:
            bool: The overlaid decision.
        """
        from mcpgateway.services.rule_catalog_service import RuleCatalogService  # pylint: disable=import-outside-toplevel

        base = await super().check_permission(
            user_email=user_email,
            permission=permission,
            resource_type=resource_type,
            resource_id=resource_id,
            team_id=team_id,
            token_teams=token_teams,
            ip_address=ip_address,
            user_agent=user_agent,
            allow_admin_bypass=allow_admin_bypass,
            check_any_team=check_any_team,
            token_is_admin=token_is_admin,
            token_roles=token_roles,
        )
        catalog = RuleCatalogService(self.db)
        overlay = catalog.evaluate_overlay(permission, self._overlay_attributes(user_email, token_teams, token_is_admin, token_roles, args=args), capability_id=resource_id)
        if overlay is None:
            return base
        if overlay:
            return True
        if allow_admin_bypass and base and await self.check_platform_admin_permission(user_email, token_teams=token_teams):
            return True
        return False

    def _overlay_attributes(self, user_email: str, token_teams: Optional[List[str]], token_is_admin: bool, token_roles: Optional[List[str]], args: Optional[dict] = None) -> dict:
        """Build predicate attributes for the overlay evaluation.

        Args:
            user_email: Principal identity.
            token_teams: Layer-1 narrowed team list, when present.
            token_is_admin: Admin flag from the token, when present.
            token_roles: Role names from the token, when present.
            args: Tool invocation arguments extracted from Mcp-Param-*
                headers (SEP-2243). Each key is the parameter name;
                the value is the header string. Absent when the caller
                has no tool context or the client did not mirror the
                annotated parameters.

        Returns:
            Nested attribute mapping for the predicate evaluator.
        """
        attributes: dict = {"authenticated": True, "subject": {"id": user_email}, "token": {"is_admin": token_is_admin}, "role": {}, "team": {}, "args": args or {}}
        for name in token_roles or []:
            attributes["role"][name] = True
        for name in token_teams or []:
            attributes["team"][name] = True
        return attributes

    def invalidate_user(self, user_email: str) -> None:
        """Clear cached permissions for a user.

        Args:
            user_email: User whose cached permissions expire now.
        """
        self.clear_user_cache(user_email)


def get_rule_provider(db: Session, audit_enabled: Optional[bool] = None) -> RuleProvider:
    """Return the rule provider selected by ``Settings.rbac_rule_provider``.

    Args:
        db: Database session for providers that read gateway state.
        audit_enabled: Passed through to the database provider; controls
            per-check audit rows on that engine.

    Returns:
        A provider implementing the :class:`RuleProvider` contract.

    Raises:
        RuntimeError: When the selected engine is not yet available.
    """
    if settings.rbac_rule_provider == "openfga":
        # The OpenFGA engine lands with its provider task; until then the
        # flag fails closed instead of silently falling back to db.
        raise RuntimeError("OpenFGA rule provider is not implemented yet; keep RBAC_RULE_PROVIDER=db")
    return DbRuleProvider(db, audit_enabled=audit_enabled)
