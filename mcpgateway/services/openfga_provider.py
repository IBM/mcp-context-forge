# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/openfga_provider.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

OpenFGA-backed Layer-2 rule provider.

Permission questions translate to OpenFGA Check calls against tuples
mirrored by :mod:`mcpgateway.services.openfga_sync`. Type-wide grants
live on the ``<type>:all`` marker object: OpenFGA rejects typed
wildcards as tuple objects. Decisions cache
client-side for ``openfga_cache_ttl_seconds``. Every transport failure
denies: the provider logs ERROR and returns False. Ownership and
team-scoped admin semantics stay on the database fallback, because the
mirrored model carries no ownership edges.

Audit parity: checks write ``PermissionAuditLog`` rows exactly like the
database provider, so Admin UI audit views keep working.
"""

# Standard
import logging
import time
from typing import Dict, List, Optional, Set, Union

# Third-Party
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import Permissions
from mcpgateway.services.openfga_client import OpenFgaClient, OpenFgaUnavailable
from mcpgateway.services.openfga_sync import build_contextual_domain_tuples, relation_for
from mcpgateway.services.rule_catalog_service import capability_for_permission
from mcpgateway.services.rule_provider import DbRuleProvider

logger = logging.getLogger(__name__)

_CacheValue = Union[bool, frozenset]
_DECISION_CACHE: Dict[tuple, tuple[float, _CacheValue]] = {}


def clear_decision_cache() -> None:
    """Drop every cached OpenFGA decision.

    The tuple sync calls this after writes so revoked grants stop
    honoring stale cache entries before the TTL expires.
    """
    _DECISION_CACHE.clear()


class OpenFgaRuleProvider(DbRuleProvider):
    """Layer-2 provider answering through the OpenFGA engine."""

    def __init__(self, db: Session) -> None:
        """Bind the provider to a session and a shared client.

        Args:
            db: Database session for the fallback ownership checks and
                audit writes.
        """
        super().__init__(db)
        self._client = OpenFgaClient()

    def _cached(self, key: tuple) -> Optional[_CacheValue]:
        """Return a fresh cached value for the key.

        Args:
            key: Cache key tuple.

        Returns:
            The cached value, or None when absent or stale.
        """
        entry = _DECISION_CACHE.get(key)
        if entry is None:
            return None
        stamp, value = entry
        if time.monotonic() - stamp > settings.openfga_cache_ttl_seconds:
            _DECISION_CACHE.pop(key, None)
            return None
        return value

    @staticmethod
    def _store(key: tuple, value: _CacheValue) -> None:
        """Cache one decision.

        Args:
            key: Cache key tuple.
            value: The engine answer or permission set.
        """
        if len(_DECISION_CACHE) > 10000:
            _DECISION_CACHE.clear()
        _DECISION_CACHE[key] = (time.monotonic(), value)

    async def _check(self, user: str, relation: str, obj: str) -> bool:
        """Answer one engine check with the fail-closed posture.

        Args:
            user: User reference.
            relation: Relation name.
            obj: Object reference.

        Returns:
            The engine answer, or False when the engine is unreachable.
        """
        try:
            return await self._client.check(user, relation, obj)
        except OpenFgaUnavailable as exc:
            logger.error("OpenFGA check failed (fail-closed deny): user=%s relation=%s object=%s error=%s", user, relation, obj, exc)
            return False

    async def check_platform_admin_permission(self, user_email: str, token_teams: Optional[List[str]] = None) -> bool:
        """Answer whether the user holds the platform_admin role.

        Args:
            user_email: Principal identity.
            token_teams: Unused; the engine answer is authoritative.

        Returns:
            True when the mirrored role assignment exists.
        """
        key = ("platform_admin", user_email)
        cached = self._cached(key)
        if cached is not None:
            return bool(cached)
        decision = await self._check(f"user:{user_email}", "assignee", "role:platform_admin")
        self._store(key, decision)
        return decision

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
        """Answer the permission question through the engine.

        Admin bypass stays local to the provider: the claims-derived
        flag and the mirrored platform_admin assignment both grant
        without consulting per-permission tuples.

        Args:
            user_email: Principal identity.
            permission: Permission string being checked.
            resource_type: Optional resource type of the target entity.
            resource_id: Optional entity id for entity-scoped rules.
            team_id: Optional team scope (engine tuples carry no team
                scoping; the type wildcard answers).
            token_teams: Layer-1 narrowed team list, when present.
            ip_address: Caller address for audit rows.
            user_agent: Caller agent for audit rows.
            allow_admin_bypass: Whether platform admins bypass the check.
            check_any_team: Unused by the engine path.
            token_is_admin: Admin flag from the token, when present.
            token_roles: Role names from the token, when present.

        Returns:
            bool: The engine decision, or False when unreachable.
        """
        if allow_admin_bypass and (token_is_admin or await self.check_platform_admin_permission(user_email)):
            return True

        capability = capability_for_permission(permission)
        relation = relation_for(permission)
        key = ("check", user_email, permission, resource_id)
        cached = self._cached(key)
        if cached is not None:
            return bool(cached)

        user = f"user:{user_email}"

        # Build contextual domain tuples from JWT claims or the database
        # fallback. The relationship model consumes them through
        # tupleToUserset; the flat model ignores them.
        contextual = build_contextual_domain_tuples(
            self.db,
            user_email,
            token_teams=token_teams,
            token_roles=token_roles,
        )

        try:
            allowed = await self._client.check(user, relation, f"{capability}:all", contextual_tuples=contextual or None)
        except OpenFgaUnavailable as exc:
            if "400" in str(exc) and contextual:
                logger.debug("Contextual tuples rejected (model mismatch); retrying without: %s", exc)
                try:
                    allowed = await self._client.check(user, relation, f"{capability}:all")
                except OpenFgaUnavailable as retry_exc:
                    logger.error("OpenFGA check failed (fail-closed deny): user=%s relation=%s error=%s", user, relation, retry_exc)
                    allowed = False
            else:
                logger.error("OpenFGA check failed (fail-closed deny): user=%s relation=%s error=%s", user, relation, exc)
                allowed = False
        if not allowed and resource_id:
            try:
                allowed = await self._client.check(user, relation, f"{capability}:{resource_id}", contextual_tuples=contextual or None)
            except OpenFgaUnavailable as exc:
                if "400" in str(exc) and contextual:
                    logger.debug("Contextual tuples rejected on entity check; retrying without: %s", exc)
                    try:
                        allowed = await self._client.check(user, relation, f"{capability}:{resource_id}")
                    except OpenFgaUnavailable as retry_exc:
                        logger.error("OpenFGA entity check failed (fail-closed deny): user=%s relation=%s error=%s", user, relation, retry_exc)
                        allowed = False
                else:
                    logger.error("OpenFGA entity check failed (fail-closed deny): user=%s relation=%s error=%s", user, relation, exc)
                    allowed = False
        if allowed and resource_id:
            blocked = await self._check(user, "blocked", f"{capability}:{resource_id}")
            if blocked:
                allowed = False
        self._store(key, allowed)

        if self.audit_enabled:
            await self._log_permission_check(
                user_email=user_email,
                permission=permission,
                resource_type=resource_type,
                resource_id=resource_id,
                team_id=team_id,
                granted=allowed,
                roles_checked={},
                ip_address=ip_address,
                user_agent=user_agent,
            )
        return allowed

    async def get_user_permissions(
        self, user_email: str, team_id: Optional[str] = None, include_all_teams: bool = False, token_teams: Optional[List[str]] = None, token_roles: Optional[List[str]] = None
    ) -> Set[str]:
        """List permission strings the engine grants the user.

        Args:
            user_email: Principal identity.
            team_id: Unused by the engine path.
            include_all_teams: Unused by the engine path.
            token_teams: Unused by the engine path.
            token_roles: Unused by the engine path.

        Returns:
            The granted permission strings, cached for the TTL. An
            unreachable engine yields the empty set (fail-closed).
        """
        key = ("permissions", user_email)
        cached = self._cached(key)
        if cached is not None and not isinstance(cached, bool):
            return set(cached)
        if await self.check_platform_admin_permission(user_email):
            granted = {Permissions.ALL_PERMISSIONS}
        else:
            granted = set()
            user = f"user:{user_email}"
            for permission in Permissions.get_all_permissions():
                relation = relation_for(permission)
                try:
                    objects = await self._client.list_objects(user, relation, capability_for_permission(permission))
                except OpenFgaUnavailable as exc:
                    logger.error("OpenFGA list-objects failed (fail-closed skip): user=%s relation=%s error=%s", user, relation, exc)
                    continue
                if objects:
                    granted.add(permission)
        self._store(key, frozenset(granted))
        return granted

    def invalidate_user(self, user_email: str) -> None:
        """Drop cached decisions for the user and the db fallback cache.

        Args:
            user_email: User whose cached state expires now.
        """
        for key in [k for k in _DECISION_CACHE if len(k) > 1 and k[1] == user_email]:
            _DECISION_CACHE.pop(key, None)
        super().invalidate_user(user_email)
