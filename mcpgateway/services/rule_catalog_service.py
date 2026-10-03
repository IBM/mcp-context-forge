# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/services/rule_catalog_service.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Rule catalog service for the Layer-2 RBAC overlay.

The catalog stores end-user-editable rules in the CPEX APL taxonomy. The
default seed mirrors the built-in role matrix one-to-one, so an unedited
catalog changes no decision. Rules apply as an overlay around the
role-based decision: a matching deny rule blocks, a matching allow rule
grants, and no matching rule leaves the decision unchanged.
"""

# Standard
import logging
from typing import Any, Optional

# Third-Party
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.bootstrap_db import DEFAULT_ROLE_DEFINITIONS
from mcpgateway.db import RbacRule
from mcpgateway.services.rule_predicate import PredicateSyntaxError, evaluate_predicate, parse_predicate

logger = logging.getLogger(__name__)

CAPABILITY_TYPES = ("tool", "resource", "prompt", "server", "gateway", "a2a_agent", "route")

_PERMISSION_CATEGORY_TO_CAPABILITY = {
    "tools": "tool",
    "resources": "resource",
    "prompts": "prompt",
    "servers": "server",
    "gateways": "gateway",
    "a2a": "a2a_agent",
}


class RuleCatalogError(ValueError):
    """Raised for invalid catalog input or protected-row operations."""


class RuleCatalogProtectedError(RuleCatalogError):
    """Raised when a caller tries to delete a system rule."""


def capability_for_permission(permission: str) -> str:
    """Map a permission string to its capability type.

    Args:
        permission: Permission string such as ``tools.read`` or ``security:read``.

    Returns:
        str: The capability type; non-entity categories map to ``route``.
    """
    category = permission.replace(":", ".").split(".")[0]
    return _PERMISSION_CATEGORY_TO_CAPABILITY.get(category, "route")


class RuleCatalogService:
    """CRUD and overlay evaluation for the ``rbac_rules`` catalog."""

    def __init__(self, db: Session) -> None:
        """Bind the service to a session.

        Args:
            db: Database session for catalog reads and writes.
        """
        self._db = db

    def list_rules(self, capability_type: Optional[str] = None, capability_id: Optional[str] = None) -> list[RbacRule]:
        """List rules, optionally filtered by capability.

        Args:
            capability_type: Filter by capability type when given.
            capability_id: Filter by entity id when given.

        Returns:
            Rules ordered by priority then name.
        """
        stmt = select(RbacRule).order_by(RbacRule.priority, RbacRule.name)
        if capability_type:
            stmt = stmt.where(RbacRule.capability_type == capability_type)
        if capability_id:
            stmt = stmt.where(RbacRule.capability_id == capability_id)
        return list(self._db.execute(stmt).scalars().all())

    def get_rule(self, rule_id: str) -> Optional[RbacRule]:
        """Return one rule by id.

        Args:
            rule_id: Rule identifier.

        Returns:
            The rule, or None when absent.
        """
        return self._db.get(RbacRule, rule_id)

    def create_rule(
        self,
        *,
        name: str,
        predicate: str,
        capability_type: str,
        effect: str,
        description: str = "",
        capability_id: Optional[str] = None,
        permission: Optional[str] = None,
        phase: str = "pre_invocation",
        priority: int = 100,
        created_by: Optional[str] = None,
    ) -> RbacRule:
        """Create a rule after validating its predicate and fields.

        Args:
            name: Unique rule name.
            predicate: Predicate in the CPEX APL subset.
            capability_type: One of :data:`CAPABILITY_TYPES`.
            effect: ``allow`` or ``deny``.
            description: Optional human-readable description.
            capability_id: Optional entity id; NULL matches all entities.
            permission: Optional permission string; NULL matches all.
            phase: ``pre_invocation`` or ``post_invocation``.
            priority: Lower values evaluate first.
            created_by: Creator identity for audit.

        Returns:
            The created rule.

        Raises:
            RuleCatalogError: On invalid fields or a duplicate name.
        """
        if capability_type not in CAPABILITY_TYPES:
            raise RuleCatalogError(f"Invalid capability_type: {capability_type}")
        if effect not in ("allow", "deny"):
            raise RuleCatalogError(f"Invalid effect: {effect}")
        if phase not in ("pre_invocation", "post_invocation"):
            raise RuleCatalogError(f"Invalid phase: {phase}")
        try:
            parse_predicate(predicate)
        except PredicateSyntaxError as exc:
            raise RuleCatalogError(f"Invalid predicate: {exc}") from exc
        rule = RbacRule(
            name=name,
            description=description,
            capability_type=capability_type,
            capability_id=capability_id,
            permission=permission,
            phase=phase,
            predicate=predicate,
            effect=effect,
            priority=priority,
            created_by=created_by,
        )
        self._db.add(rule)
        try:
            self._db.flush()
        except IntegrityError as exc:
            self._db.rollback()
            raise RuleCatalogError(f"Rule name already exists: {name}") from exc
        logger.info("RBAC rule created: name=%s capability=%s/%s effect=%s", name, capability_type, capability_id or "*", effect)
        return rule

    def update_rule(self, rule_id: str, **fields: Any) -> RbacRule:
        """Update editable fields of a rule.

        Args:
            rule_id: Rule identifier.
            **fields: Fields to set; the predicate is validated first.

        Returns:
            The updated rule.

        Raises:
            RuleCatalogError: When the rule is absent or a field is invalid.
        """
        rule = self.get_rule(rule_id)
        if rule is None:
            raise RuleCatalogError(f"Rule not found: {rule_id}")
        if "capability_type" in fields and fields["capability_type"] not in CAPABILITY_TYPES:
            raise RuleCatalogError(f"Invalid capability_type: {fields['capability_type']}")
        if "effect" in fields and fields["effect"] not in ("allow", "deny"):
            raise RuleCatalogError(f"Invalid effect: {fields['effect']}")
        if "phase" in fields and fields["phase"] not in ("pre_invocation", "post_invocation"):
            raise RuleCatalogError(f"Invalid phase: {fields['phase']}")
        if "predicate" in fields:
            try:
                parse_predicate(fields["predicate"])
            except PredicateSyntaxError as exc:
                raise RuleCatalogError(f"Invalid predicate: {exc}") from exc
        for key, value in fields.items():
            setattr(rule, key, value)
        self._db.flush()
        return rule

    def delete_rule(self, rule_id: str) -> None:
        """Delete a rule.

        Args:
            rule_id: Rule identifier.

        Raises:
            RuleCatalogError: When the rule is absent.
            RuleCatalogProtectedError: When the rule is a system rule.
        """
        rule = self.get_rule(rule_id)
        if rule is None:
            raise RuleCatalogError(f"Rule not found: {rule_id}")
        if rule.is_system:
            raise RuleCatalogProtectedError(f"System rules cannot be deleted: {rule.name}")
        self._db.delete(rule)
        self._db.flush()

    def evaluate_overlay(self, permission: str, attributes: dict[str, Any], *, capability_id: Optional[str] = None) -> Optional[bool]:
        """Apply matching rules as an overlay decision.

        Args:
            permission: Permission string of the current check.
            attributes: Predicate attributes built from the caller context.
            capability_id: Entity id when the check targets one entity.

        Returns:
            True when a matching allow rule holds, False when a matching
            deny rule holds, None when no active rule matches.
        """
        capability_type = capability_for_permission(permission)
        stmt = (
            select(RbacRule)
            .where(
                RbacRule.is_active.is_(True),
                RbacRule.capability_type == capability_type,
                RbacRule.capability_id.is_(None) | (RbacRule.capability_id == capability_id),
                RbacRule.permission.is_(None) | (RbacRule.permission == permission),
            )
            .order_by(RbacRule.priority, RbacRule.name)
        )
        for rule in self._db.execute(stmt).scalars():
            try:
                holds = evaluate_predicate(rule.predicate, attributes)
            except PredicateSyntaxError:
                logger.error("Stored predicate failed to parse; treating as no match: rule=%s", rule.name)
                continue
            if holds:
                logger.debug("Rule catalog overlay decision: rule=%s effect=%s", rule.name, rule.effect)
                return rule.effect == "allow"
        return None

    @staticmethod
    def export_builtin_matrix() -> list[dict[str, Any]]:
        """Export the built-in role matrix as catalog rule dicts.

        Returns:
            One rule dict per (role, permission) pair of the built-in
            roles, each with predicate ``role.<name>`` and effect allow.
        """
        rules: list[dict[str, Any]] = []
        for role in DEFAULT_ROLE_DEFINITIONS:
            permissions = role.get("permissions", [])
            if "*" in permissions:
                for capability in CAPABILITY_TYPES:
                    rules.append({"name": f"default-{role['name']}-{capability}", "capability_type": capability, "permission": None, "predicate": f"role.{role['name']}", "effect": "allow"})
                continue
            for permission in permissions:
                rules.append(
                    {
                        "name": f"default-{role['name']}-{permission.replace(':', '-').replace('.', '-')}",
                        "capability_type": capability_for_permission(permission),
                        "permission": permission,
                        "predicate": f"role.{role['name']}",
                        "effect": "allow",
                    }
                )
        return rules

    def reseed_defaults(self, *, created_by: str = "system") -> int:
        """Insert missing system rules for the built-in matrix.

        Args:
            created_by: Identity recorded on seeded rows.

        Returns:
            Number of rules inserted.
        """
        inserted = 0
        for spec in self.export_builtin_matrix():
            exists = self._db.execute(select(RbacRule.id).where(RbacRule.name == spec["name"])).scalar_one_or_none()
            if exists:
                continue
            self._db.add(
                RbacRule(
                    name=spec["name"],
                    description="Built-in role matrix seed",
                    capability_type=spec["capability_type"],
                    capability_id=None,
                    permission=spec["permission"],
                    phase="pre_invocation",
                    predicate=spec["predicate"],
                    effect="allow",
                    priority=1000,
                    is_active=True,
                    is_system=True,
                    created_by=created_by,
                )
            )
            inserted += 1
        self._db.flush()
        return inserted
