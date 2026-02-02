"""Native RBAC / ABAC engine adapter – pure Python, zero external deps.

Design goals
------------
* **No sidecar.**  This engine runs entirely in-process.  It is the fastest
  engine by a large margin (sub-millisecond) and the only one that can
  enumerate permissions via ``get_permissions()``.
* **Rule format.**  Rules are plain Python dicts.  They can be loaded from
  a JSON file at startup or registered programmatically.  Each rule has:

      {
          "id":             "rule-001",
          "roles":          ["admin", "developer"],   # ANY of these roles grants access
          "actions":        ["tools.invoke"],          # glob-style matching supported
          "resource_types": ["tool"],                  # or ["*"] for any type
          "resource_ids":   ["*"],                     # specific IDs or wildcard
          "conditions":     { ... }                    # optional attribute checks
      }

* **Conditions** are evaluated as simple key-path equality or set-membership
  checks against the ``Subject`` and ``Context`` objects.  Example::

      "conditions": {
          "subject.mfa_verified": true,
          "context.ip_prefix": "10.0.0."     # startswith check
      }

* **Deny rules** are also supported.  A deny rule has the same shape but its
  ``id`` starts with ``deny:``.  Deny rules are evaluated *before* allow rules
  (fail-closed).
"""

from __future__ import annotations

import fnmatch
import logging
import time
from typing import Any, Dict, List

from ..adapter import PolicyEngineAdapter
from ..pdp_models import (
    Context,
    Decision,
    EngineDecision,
    EngineHealthReport,
    EngineStatus,
    EngineType,
    Permission,
    Resource,
    Subject,
)

logger = logging.getLogger(__name__)

# Type alias for a single rule dict
Rule = Dict[str, Any]


class NativeRBACAdapter(PolicyEngineAdapter):
    """Pure-Python RBAC/ABAC engine.

    Parameters
    ----------
    settings : dict, optional
        May contain ``rules`` (list of Rule dicts) or ``rules_file`` (path
        to a JSON/YAML file).  If neither is supplied the engine starts
        with an empty rule-set (everything denied by default).
    """

    def __init__(self, settings: Dict[str, Any] | None = None):
        self._settings = settings or {}
        self._rules: List[Rule] = []
        self._load_rules()

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def engine_type(self) -> EngineType:
        return EngineType.NATIVE

    # ------------------------------------------------------------------
    # Rule loading
    # ------------------------------------------------------------------

    def _load_rules(self) -> None:
        """Populate ``self._rules`` from settings."""
        # Inline rules take precedence
        if "rules" in self._settings:
            self._rules = list(self._settings["rules"])
            logger.info("NativeRBAC: loaded %d inline rules", len(self._rules))
            return

        # File-based rules
        rules_file = self._settings.get("rules_file")
        if rules_file:
            import json as _json

            try:
                with open(rules_file, encoding="utf-8") as fh:
                    data = _json.load(fh)
                self._rules = data if isinstance(data, list) else data.get("rules", [])
                logger.info("NativeRBAC: loaded %d rules from %s", len(self._rules), rules_file)
            except (OSError, _json.JSONDecodeError) as exc:
                logger.error("NativeRBAC: failed to load rules file %s: %s", rules_file, exc)
                self._rules = []
            return

        logger.info("NativeRBAC: no rules configured – all requests will be denied")

    def add_rule(self, rule: Rule) -> None:
        """Programmatically add a rule at runtime."""
        self._rules.append(rule)

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule by ID.  Returns True if found and removed."""
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.get("id") != rule_id]
        return len(self._rules) < before

    # ------------------------------------------------------------------
    # Matching helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _role_matches(rule: Rule, subject: Subject) -> bool:
        """Check if subject holds any of the roles required by the rule."""
        rule_roles = rule.get("roles", ["*"])
        if "*" in rule_roles:
            return True
        return bool(set(rule_roles) & set(subject.roles))

    @staticmethod
    def _action_matches(rule: Rule, action: str) -> bool:
        """Glob-match the action against rule's action patterns."""
        patterns = rule.get("actions", ["*"])
        return any(fnmatch.fnmatch(action, p) for p in patterns)

    @staticmethod
    def _resource_matches(rule: Rule, resource: Resource) -> bool:
        """Check resource type and ID against the rule."""
        type_patterns = rule.get("resource_types", ["*"])
        id_patterns = rule.get("resource_ids", ["*"])

        type_ok = "*" in type_patterns or resource.type in type_patterns
        id_ok = "*" in id_patterns or any(fnmatch.fnmatch(resource.id, p) for p in id_patterns)
        return type_ok and id_ok

    @staticmethod
    def _conditions_match(rule: Rule, subject: Subject, context: Context) -> bool:
        """Evaluate the ``conditions`` block against subject and context.

        Supports:
        * Exact equality:   ``"subject.mfa_verified": true``
        * Startswith:        ``"context.ip_prefix": "10.0.0."``
        * Set membership:    ``"subject.roles_contains": "admin"``
        """
        conditions = rule.get("conditions", {})
        if not conditions:
            return True  # no conditions = always matches

        # Build a flat lookup of subject + context attributes
        flat: Dict[str, Any] = {
            "subject.email": subject.email,
            "subject.mfa_verified": subject.mfa_verified,
            "subject.team_id": subject.team_id,
            "subject.clearance_level": subject.clearance_level,
            "context.ip": context.ip,
            "context.session_id": context.session_id,
            "context.user_agent": context.user_agent,
        }
        # Expose roles as a set for membership checks
        flat["subject.roles"] = set(subject.roles)

        for key, expected in conditions.items():
            # Special: startswith checks (key ends with _prefix)
            if key.endswith("_prefix"):
                base_key = key[: -len("_prefix")]
                actual = flat.get(base_key, "")
                if not str(actual).startswith(str(expected)):
                    return False
                continue

            # Special: set membership (key ends with _contains)
            if key.endswith("_contains"):
                base_key = key[: -len("_contains")]
                actual = flat.get(base_key, set())
                if expected not in actual:
                    return False
                continue

            # Default: exact equality
            actual = flat.get(key)
            if actual != expected:
                return False

        return True

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    async def evaluate(
        self,
        subject: Subject,
        action: str,
        resource: Resource,
        context: Context,
    ) -> EngineDecision:
        start = time.perf_counter()

        # --- Phase 1: deny rules (checked first – fail closed) ---
        for rule in self._rules:
            rule_id = rule.get("id", "")
            if not rule_id.startswith("deny:"):
                continue
            if (
                self._role_matches(rule, subject)
                and self._action_matches(rule, action)
                and self._resource_matches(rule, resource)
                and self._conditions_match(rule, subject, context)
            ):
                duration = (time.perf_counter() - start) * 1000
                return EngineDecision(
                    engine=EngineType.NATIVE,
                    decision=Decision.DENY,
                    reason=rule.get("reason", f"Denied by rule {rule_id}"),
                    matching_policies=[rule_id],
                    duration_ms=round(duration, 2),
                )

        # --- Phase 2: allow rules ---
        matched_policies: List[str] = []
        for rule in self._rules:
            rule_id = rule.get("id", "")
            if rule_id.startswith("deny:"):
                continue
            if (
                self._role_matches(rule, subject)
                and self._action_matches(rule, action)
                and self._resource_matches(rule, resource)
                and self._conditions_match(rule, subject, context)
            ):
                matched_policies.append(rule_id)

        duration = (time.perf_counter() - start) * 1000

        if matched_policies:
            return EngineDecision(
                engine=EngineType.NATIVE,
                decision=Decision.ALLOW,
                reason=f"Allowed by rules: {', '.join(matched_policies)}",
                matching_policies=matched_policies,
                duration_ms=round(duration, 2),
            )

        # No rule matched → deny (fail closed)
        return EngineDecision(
            engine=EngineType.NATIVE,
            decision=Decision.DENY,
            reason="Native RBAC: no matching allow rule (fail closed)",
            duration_ms=round(duration, 2),
        )

    # ------------------------------------------------------------------
    # Permission enumeration
    # ------------------------------------------------------------------

    async def get_permissions(self, subject: Subject, context: Context) -> List[Permission]:
        """Return every permission the subject holds according to current rules."""
        perms: List[Permission] = []

        for rule in self._rules:
            rule_id = rule.get("id", "")
            if rule_id.startswith("deny:"):
                continue  # deny rules don't grant permissions

            if not self._role_matches(rule, subject):
                continue
            if not self._conditions_match(rule, subject, context):
                continue

            # Expand action × resource_type × resource_id into Permission objects
            actions = rule.get("actions", ["*"])
            res_types = rule.get("resource_types", ["*"])
            res_ids = rule.get("resource_ids", ["*"])

            for act in actions:
                for rt in res_types:
                    for rid in res_ids:
                        perms.append(
                            Permission(
                                action=act,
                                resource_type=rt,
                                resource_id=rid if rid != "*" else None,
                                granted_by=rule_id,
                                conditions=rule.get("conditions", {}),
                            )
                        )

        return perms

    # ------------------------------------------------------------------
    # Health  (always healthy – no external dependency)
    # ------------------------------------------------------------------

    async def health_check(self) -> EngineHealthReport:
        return EngineHealthReport(
            engine=EngineType.NATIVE,
            status=EngineStatus.HEALTHY,
            latency_ms=0.0,
            detail=f"{len(self._rules)} rules loaded",
        )
