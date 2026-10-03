# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/openfga_sync.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tuple synchronization from the gateway database to OpenFGA.

The gateway database stays the source of truth. Bootstrap ensures the
store and the authorization model exist. The mirror writes role
assignments, team memberships, role-permission grants, and simple
entity-scoped catalog rules as tuples. Predicates beyond plain
``role.`` and ``team.`` truthiness stay in the database: OpenFGA tuples
carry no predicate grammar, so the provider overlay keeps evaluating
them.

Authorization model shape: every capability type gains one relation per
permission verb mapped to it. Each relation is the set of direct
subjects minus the ``blocked`` deny set. Direct subjects are users,
team members, and role assignees.
"""

# Standard
import logging
from typing import Any

# Third-Party
from sqlalchemy import select
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import settings
from mcpgateway.db import EmailTeamMember, Permissions, RbacRule, Role, SessionLocal, UserRole
from mcpgateway.services.openfga_client import OpenFgaClient, OpenFgaUnavailable
from mcpgateway.services.rule_catalog_service import capability_for_permission
from mcpgateway.services.rule_predicate import Truthiness, parse_predicate

logger = logging.getLogger(__name__)

ENTITY_TYPES = ("tool", "resource", "prompt", "server", "gateway", "a2a_agent", "route")

_GRANT_SUBJECTS = [{"type": "user"}, {"type": "team", "relation": "member"}, {"type": "role", "relation": "assignee"}]


def relation_for(permission: str) -> str:
    """Normalize a permission string to a relation name.

    Args:
        permission: Permission string such as ``tools.read`` or ``security:read``.

    Returns:
        The relation name, for example ``tools_read``.
    """
    return permission.replace(":", "_").replace(".", "_")


def build_type_definitions() -> list[dict[str, Any]]:
    """Build the authorization model from the permission constants.

    Returns:
        Type definitions in the OpenFGA JSON form, schema 1.1.
    """
    permissions = Permissions.get_all_permissions()
    by_type: dict[str, list[str]] = {entity: [] for entity in ENTITY_TYPES}
    for permission in permissions:
        by_type[capability_for_permission(permission)].append(permission)

    type_definitions: list[dict[str, Any]] = [
        {"type": "user"},
        {"type": "team", "relations": {"member": {"this": {}}}, "metadata": {"relations": {"member": {"directly_related_user_types": [{"type": "user"}]}}}},
        {"type": "role", "relations": {"assignee": {"this": {}}}, "metadata": {"relations": {"assignee": {"directly_related_user_types": [{"type": "user"}]}}}},
    ]
    for entity in ENTITY_TYPES:
        relations: dict[str, Any] = {"blocked": {"this": {}}}
        metadata: dict[str, Any] = {"relations": {"blocked": {"directly_related_user_types": list(_GRANT_SUBJECTS)}}}
        for permission in by_type[entity]:
            relations[relation_for(permission)] = {"difference": {"base": {"this": {}}, "subtract": {"computedUserset": {"relation": "blocked"}}}}
            metadata["relations"][relation_for(permission)] = {"directly_related_user_types": list(_GRANT_SUBJECTS)}
        type_definitions.append({"type": entity, "relations": relations, "metadata": metadata})
    return type_definitions


def _simple_subject(predicate: str) -> str | None:
    """Map a plain truthiness predicate to a tuple subject.

    Args:
        predicate: Predicate string from the catalog.

    Returns:
        A subject such as ``role:dev#assignee`` or ``team:eng#member``,
        or None when the predicate is richer than plain truthiness.
    """
    try:
        node = parse_predicate(predicate)
    except ValueError:
        return None
    if not isinstance(node, Truthiness):
        return None
    kind, _, name = node.attr.partition(".")
    if kind == "role" and name:
        return f"role:{name}#assignee"
    if kind == "team" and name:
        return f"team:{name}#member"
    return None


class OpenFgaSyncService:
    """Mirrors gateway identity and rule state into OpenFGA tuples."""

    def __init__(self, db: Session, client: OpenFgaClient) -> None:
        """Bind the sync to a session and an API client.

        Args:
            db: Database session reading the source of truth.
            client: Configured OpenFGA client.
        """
        self._db = db
        self._client = client

    def desired_tuples(self) -> set[tuple[str, str, str]]:
        """Compute the full desired tuple set from the database.

        Returns:
            Set of (user, relation, object) tuple keys.
        """
        tuples: set[tuple[str, str, str]] = set()
        roles = {role.id: role for role in self._db.execute(select(Role).where(Role.is_active.is_(True))).scalars()}
        for assignment in self._db.execute(select(UserRole).where(UserRole.is_active.is_(True))).scalars():
            role = roles.get(assignment.role_id)
            if role is not None:
                tuples.add((f"user:{assignment.user_email}", "assignee", f"role:{role.name}"))
        for membership in self._db.execute(select(EmailTeamMember).where(EmailTeamMember.is_active.is_(True))).scalars():
            tuples.add((f"user:{membership.user_email}", "member", f"team:{membership.team_id}"))
        all_permissions = Permissions.get_all_permissions()
        for role in roles.values():
            granted = all_permissions if "*" in (role.permissions or []) else list(role.permissions or [])
            for permission in granted:
                tuples.add((f"role:{role.name}#assignee", relation_for(permission), f"{capability_for_permission(permission)}:*"))
        for rule in self._db.execute(select(RbacRule).where(RbacRule.is_active.is_(True), RbacRule.capability_id.is_not(None))).scalars():
            subject = _simple_subject(rule.predicate)
            if subject is None:
                continue
            relations = [relation_for(rule.permission)] if rule.permission else [relation_for(p) for p in all_permissions if capability_for_permission(p) == rule.capability_type]
            for rel in relations:
                tuples.add((subject, "blocked" if rule.effect == "deny" else rel, f"{rule.capability_type}:{rule.capability_id}"))
        return tuples

    async def bootstrap(self) -> None:
        """Ensure the store and authorization model exist and match.

        Raises:
            OpenFgaUnavailable: When the API cannot be reached.
        """
        if not settings.openfga_store_id:
            stores = await self._client.list_stores(settings.openfga_store_name)
            store = stores[0] if stores else await self._client.create_store(settings.openfga_store_name)
            settings.openfga_store_id = str(store["id"])
            logger.info("OpenFGA store resolved: id=%s name=%s", settings.openfga_store_id, settings.openfga_store_name)
        latest = await self._client.latest_model()
        if latest is None or latest.get("type_definitions") != build_type_definitions():
            model_id = await self._client.write_model(build_type_definitions())
            logger.info("OpenFGA authorization model written: id=%s", model_id)

    async def full_resync(self) -> int:
        """Converge stored tuples to the desired set.

        Returns:
            Number of tuple writes and deletes applied.
        """
        desired = self.desired_tuples()
        stored_raw = await self._client.read_tuples()
        stored = {(t["user"], t["relation"], t["object"]) for t in stored_raw if isinstance(t, dict) and all(k in t for k in ("user", "relation", "object"))}
        writes = [{"user": u, "relation": r, "object": o} for (u, r, o) in sorted(desired - stored)]
        deletes = [{"user": u, "relation": r, "object": o} for (u, r, o) in sorted(stored - desired)]
        await self._client.write_tuples(writes, deletes)
        if writes or deletes:
            from mcpgateway.services.openfga_provider import clear_decision_cache  # pylint: disable=import-outside-toplevel

            clear_decision_cache()
            logger.info("OpenFGA resync applied: writes=%d deletes=%d", len(writes), len(deletes))
        return len(writes) + len(deletes)

    async def sync_now(self, reason: str) -> int:
        """Run a full resync, logging failures without raising.

        Args:
            reason: Trigger description for the log line.

        Returns:
            Number of changes applied, or -1 when the engine was unreachable.
        """
        try:
            return await self.full_resync()
        except OpenFgaUnavailable as exc:
            logger.error("OpenFGA sync failed (%s): %s", reason, exc)
            return -1


def openfga_sync_enabled() -> bool:
    """Say whether the OpenFGA engine participates in this deployment.

    Returns:
        True when the provider is openfga or shadow mode is on.
    """
    return settings.rbac_rule_provider == "openfga" or settings.rbac_rule_provider_shadow


async def openfga_sync_after_commit(db: Session, reason: str) -> None:
    """Resync tuples after an identity mutation, without failing the caller.

    Args:
        db: The caller's session, used read-only for the mirror query.
        reason: Trigger description for the log line.
    """
    if not openfga_sync_enabled():
        return
    try:
        await OpenFgaSyncService(db, OpenFgaClient()).sync_now(reason)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("OpenFGA post-commit sync failed (%s): %s", reason, exc)


async def openfga_reconciliation_loop() -> None:
    """Converge tuples periodically while the engine is enabled.

    Covers drift that bypasses the service hooks, such as alembic data
    migrations editing role permissions with raw SQL.
    """
    import asyncio  # pylint: disable=import-outside-toplevel

    while True:
        if openfga_sync_enabled():
            try:
                with SessionLocal() as db:
                    service = OpenFgaSyncService(db, OpenFgaClient())
                    await service.bootstrap()
                    await service.sync_now("reconciliation")
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error("OpenFGA reconciliation failed: %s", exc)
        await asyncio.sleep(settings.openfga_reconcile_seconds)
