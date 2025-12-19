# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/plugins/framework/routing/rule_resolver.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Claude Code

Rule-Based Plugin Resolver.
Implements flat, declarative rule matching for plugin routing using
exact matches (fast path), tag-based matching, and complex expressions.
"""

# Standard
import logging
from typing import Any, Optional

# Third-Party
from pydantic import BaseModel

# First-Party
from mcpgateway.plugins.framework.hooks.registry import get_hook_registry
from mcpgateway.plugins.framework.models import (
    EntityType,
    PluginAttachment,
    PluginHookRule,
)
from mcpgateway.plugins.framework.routing.evaluator import (
    EvaluationContext,
    PolicyEvaluator,
)

logger = logging.getLogger(__name__)


class RuleMatchContext(BaseModel):
    """Context for rule matching.

    Contains information about the entity being matched against rules.

    Attributes:
        name: Entity name.
        entity_type: Entity type (tool, prompt, resource, agent, http).
        entity_id: Optional entity ID.
        tags: Entity tags.
        metadata: Entity metadata.
        server_name: Server name.
        server_id: Server ID.
        gateway_id: Gateway ID.
        payload: Full payload dict for accessing any field.
        user: User making the request.
        tenant_id: Tenant ID.

    Examples:
        >>> ctx = RuleMatchContext(
        ...     name="create_customer",
        ...     entity_type="tool",
        ...     tags=["customer", "pii"],
        ...     metadata={"risk_level": "high"},
        ...     server_name="api-server",
        ...     payload={"args": {"email": "test@example.com"}}
        ... )
        >>> ctx.name
        'create_customer'
        >>> ctx.tags
        ['customer', 'pii']
    """

    name: str
    entity_type: str
    entity_id: Optional[str] = None
    tags: list[str] = []
    metadata: dict[str, Any] = {}
    server_name: Optional[str] = None
    server_id: Optional[str] = None
    gateway_id: Optional[str] = None
    payload: dict[str, Any] = {}
    user: Optional[str] = None
    tenant_id: Optional[str] = None


class RuleBasedResolver:
    """Resolves plugins using flat, declarative rule-based matching with caching.

    Uses two-level caching strategy:
    1. Static resolution (cached): Match rules by name/tags/server, return plugin attachments
    2. Runtime filtering: Evaluate 'when' clauses on cached plugins with request context

    The cache key is (entity_type, entity_name, hook_type) and stores a list of
    PluginAttachments. Rule-level 'when' clauses are transferred to each plugin
    attachment and evaluated at runtime, not during resolution.

    Examples:
        >>> from mcpgateway.plugins.framework.models import EntityType, PluginAttachment, PluginHookRule
        >>> resolver = RuleBasedResolver()

        >>> # Define rules
        >>> rules = [
        ...     PluginHookRule(
        ...         entities=[EntityType.TOOL],
        ...         tags=["customer", "pii"],
        ...         plugins=[
        ...             PluginAttachment(name="pii_filter", priority=10),
        ...             PluginAttachment(name="audit_logger", priority=20)
        ...         ]
        ...     ),
        ...     PluginHookRule(
        ...         entities=[EntityType.TOOL],
        ...         name="process_payment",
        ...         plugins=[
        ...             PluginAttachment(name="fraud_detector", priority=5)
        ...         ]
        ...     )
        ... ]

        >>> # Match entity against rules
        >>> ctx = RuleMatchContext(
        ...     name="create_customer",
        ...     entity_type="tool",
        ...     tags=["customer", "pii"],
        ...     server_name="api-server"
        ... )
        >>> attachments = resolver.resolve_for_entity(rules, ctx)
        >>> len(attachments)
        2
        >>> attachments[0].name
        'pii_filter'
    """

    def __init__(self):
        """Initialize the rule-based resolver.

        Note: Caching is handled by PluginManager, not here.
        """
        self.evaluator = PolicyEvaluator()

    def resolve_for_entity(
        self,
        rules: list[PluginHookRule],
        context: RuleMatchContext,
        hook_type: Optional[str] = None,
        eval_context: Optional[EvaluationContext] = None,
        merge_strategy: str = "most_specific",
    ) -> list[PluginAttachment]:
        """Resolve plugins for an entity with optional runtime filtering.

        This method performs:
        1. Static matching: Match rules by name/tags/server (no 'when' evaluation)
        2. Runtime filtering (optional): Evaluate 'when' clauses with context

        Note: Caching is handled by PluginManager, not here.

        Args:
            rules: List of plugin hook rules to evaluate.
            context: Context about the entity being matched.
            hook_type: Optional hook type (for logging/debugging).
            eval_context: Optional evaluation context for 'when' clause filtering.
            merge_strategy: Strategy for merging matching rules - "most_specific" (default) or "merge_all".

        Returns:
            List of PluginAttachments to apply to the entity, sorted by priority.

        Examples:
            >>> resolver = RuleBasedResolver()
            >>> rules = [
            ...     PluginHookRule(
            ...         entities=[EntityType.TOOL],
            ...         tags=["pii"],
            ...         plugins=[PluginAttachment(name="pii_filter", priority=10)]
            ...     )
            ... ]
            >>> ctx = RuleMatchContext(
            ...     name="get_customer",
            ...     entity_type="tool",
            ...     tags=["pii"]
            ... )
            >>> attachments = resolver.resolve_for_entity(rules, ctx)
            >>> len(attachments)
            1
            >>> attachments[0].name
            'pii_filter'

            >>> # With runtime filtering
            >>> rule_with_when = PluginHookRule(
            ...     entities=[EntityType.TOOL],
            ...     when="args.size > 1000",
            ...     plugins=[PluginAttachment(name="size_validator", priority=10)]
            ... )
            >>> eval_ctx = EvaluationContext(args={"size": 1500})
            >>> attachments_filtered = resolver.resolve_for_entity(
            ...     [rule_with_when], ctx, eval_context=eval_ctx
            ... )
            >>> len(attachments_filtered)
            1
        """
        # Perform static resolution (no 'when' evaluation)
        static_plugins = self._resolve_static(rules, context, hook_type, merge_strategy)

        # Apply runtime filtering (evaluate 'when' clauses) if context provided
        if eval_context:
            filtered_plugins = self._filter_runtime(static_plugins, eval_context)
            return filtered_plugins

        return static_plugins

    def _resolve_static(
        self,
        rules: list[PluginHookRule],
        context: RuleMatchContext,
        hook_type: Optional[str] = None,
        merge_strategy: str = "most_specific",
    ) -> list[PluginAttachment]:
        """Resolve plugins statically (no 'when' clause evaluation).

        Transfers rule-level 'when' clauses to plugin attachments for runtime evaluation.
        Implements reverse_order_on_post for symmetric hook wrapping.

        Args:
            rules: List of plugin hook rules to evaluate.
            context: Context about the entity being matched.
            hook_type: Optional hook type to check for POST hooks and hook filtering.

        Returns:
            List of PluginAttachments sorted by priority, with 'when' clauses transferred.
        """
        matching_rules: list[tuple[PluginHookRule, int]] = []

        # Find all matching rules with their specificity (skip 'when' evaluation)
        for rule in rules:
            # Filter by hooks if specified
            if rule.hooks and hook_type:
                if hook_type not in rule.hooks:
                    continue

            if self._rule_matches_static(rule, context):
                specificity = self._calculate_specificity(rule)
                matching_rules.append((rule, specificity))

        # Sort by priority (explicit priority first, then specificity)
        matching_rules.sort(
            key=lambda x: (
                x[0].priority if x[0].priority is not None else 999999,
                -x[1],  # Higher specificity first
            )
        )

        # Apply merge strategy
        if matching_rules and merge_strategy == "most_specific":
            # Filter: Keep only rules with the highest specificity level
            # This ensures more specific rules (e.g., with name filters) take precedence
            # over less specific rules (e.g., only infrastructure filters)
            max_specificity = max(specificity for _, specificity in matching_rules)
            matching_rules = [(rule, spec) for rule, spec in matching_rules if spec == max_specificity]
        # else: merge_strategy == "merge_all" -> use all matching rules

        # Check if this is a POST hook for reverse ordering
        is_post_hook = False
        if hook_type:
            registry = get_hook_registry()
            is_post_hook = registry.is_post_hook(hook_type)

        # Merge plugins from matching rules
        merged_attachments: list[PluginAttachment] = []

        # Note: We DO NOT deduplicate by plugin name here because the same plugin
        # can appear multiple times with different configurations, creating different instances.
        # The PluginManager will create separate instances based on config hashes.

        for rule, _ in matching_rules:
            for plugin_attachment in rule.plugins:

                # Transfer rule-level 'when' to plugin attachment if not already set
                if rule.when and not plugin_attachment.when:
                    # Create a copy with rule's 'when' clause for runtime evaluation
                    attachment_with_when = PluginAttachment(
                        name=plugin_attachment.name,
                        priority=plugin_attachment.priority,
                        post_priority=plugin_attachment.post_priority,
                        hooks=plugin_attachment.hooks,
                        when=rule.when,  # Transfer from rule for runtime evaluation
                        apply_to=plugin_attachment.apply_to,
                        override=plugin_attachment.override,
                        mode=plugin_attachment.mode,
                        config=plugin_attachment.config,
                    )
                    merged_attachments.append(attachment_with_when)
                else:
                    merged_attachments.append(plugin_attachment)

        # Sort final list by plugin priority
        merged_attachments.sort(key=lambda p: p.priority)

        # Apply reverse ordering for POST hooks if any rule requested it
        if is_post_hook:
            # Collect reverse_order_on_post settings from all matching rules
            reverse_settings = [rule.reverse_order_on_post for rule, _ in matching_rules]
            should_reverse = any(reverse_settings)

            # Warn if settings are inconsistent across matching rules
            if should_reverse and not all(reverse_settings):
                logger.warning(
                    f"Inconsistent reverse_order_on_post settings for entity '{context.name}': "
                    f"some rules have reverse_order_on_post=True while others don't. "
                    f"All plugins will be reversed because at least one rule requested it. "
                    f"Consider setting reverse_order_on_post consistently across all matching rules."
                )

            if should_reverse:
                merged_attachments = list(reversed(merged_attachments))
                logger.debug(f"Reversed plugin order for POST hook '{hook_type}' to create symmetric wrapping: " f"{[p.name for p in merged_attachments]}")

        return merged_attachments

    def _filter_runtime(
        self,
        static_plugins: list[PluginAttachment],
        context: EvaluationContext,
    ) -> list[PluginAttachment]:
        """Filter plugins at runtime by evaluating 'when' clauses.

        Args:
            static_plugins: Pre-resolved plugins from cache (with 'when' transferred from rules).
            context: Evaluation context for 'when' clauses.

        Returns:
            Filtered list of plugins.
        """
        filtered = []

        for plugin in static_plugins:
            # Evaluate 'when' clause if present (transferred from rule)
            if plugin.when:
                try:
                    if not self.evaluator.evaluate(plugin.when, context):
                        logger.debug(f"Skipping plugin {plugin.name}: " f"when clause '{plugin.when}' evaluated to False")
                        continue
                except Exception as e:
                    logger.error(f"Failed to evaluate when clause for plugin {plugin.name}: {e}. " "Skipping plugin.")
                    continue

            filtered.append(plugin)

        return filtered

    def _rule_matches_static(self, rule: PluginHookRule, context: RuleMatchContext) -> bool:
        """Check if a rule matches using static criteria only (no 'when' evaluation).

        Uses fast-path matching for name, tags, and infrastructure filters.
        Does NOT evaluate 'when' expressions - those are deferred to runtime.

        Args:
            rule: The rule to evaluate.
            context: The entity context.

        Returns:
            True if the rule matches statically, False otherwise.
        """
        # Check entity type match (None = HTTP-level)
        if rule.entities is not None:
            entity_type_enum = self._get_entity_type_enum(context.entity_type)
            if entity_type_enum not in rule.entities:
                return False

        # Check infrastructure filters
        if not self._infrastructure_matches(rule, context):
            return False

        # FAST PATH: Exact name match
        if rule.name is not None:
            if isinstance(rule.name, list):
                if context.name not in rule.name:
                    return False
            elif context.name != rule.name:
                return False

        # FAST PATH: Tag match (set intersection)
        if rule.tags:
            rule_tags_set = set(rule.tags)
            context_tags_set = set(context.tags)
            if not rule_tags_set.intersection(context_tags_set):
                return False

        # Skip 'when' evaluation - that happens at runtime
        return True

    def _infrastructure_matches(self, rule: PluginHookRule, context: RuleMatchContext) -> bool:
        """Check if infrastructure filters match.

        Args:
            rule: The rule with infrastructure filters.
            context: The entity context.

        Returns:
            True if infrastructure filters match, False otherwise.
        """
        # Check server_name filter
        if rule.server_name is not None:
            if isinstance(rule.server_name, list):
                if context.server_name not in rule.server_name:
                    return False
            elif context.server_name != rule.server_name:
                return False

        # Check server_id filter
        if rule.server_id is not None:
            if isinstance(rule.server_id, list):
                if context.server_id not in rule.server_id:
                    return False
            elif context.server_id != rule.server_id:
                return False

        # Check gateway_id filter
        if rule.gateway_id is not None:
            if isinstance(rule.gateway_id, list):
                if context.gateway_id not in rule.gateway_id:
                    return False
            elif context.gateway_id != rule.gateway_id:
                return False

        return True

    def _calculate_specificity(self, rule: PluginHookRule) -> int:
        """Calculate specificity score for a rule.

        Higher scores indicate more specific rules.
        - Exact name match: 1000
        - Tag match: 100
        - Hook type filter: 50
        - When expression: 10
        - Entity type only: 0

        Args:
            rule: The rule to score.

        Returns:
            Specificity score.
        """
        score = 0

        # Exact name match is most specific
        if rule.name is not None:
            score += 1000

        # Tag match is medium specificity
        if rule.tags:
            score += 100

        # Hook type filter is medium-low specificity
        if rule.hooks:
            score += 50

        # When expression is lower specificity
        if rule.when:
            score += 10

        return score

    def _get_entity_type_enum(self, entity_type: str) -> EntityType:
        """Convert entity type string to EntityType enum.

        Args:
            entity_type: Entity type string.

        Returns:
            EntityType enum value.

        Raises:
            ValueError: If entity type is invalid.
        """
        type_map = {
            "tool": EntityType.TOOL,
            "prompt": EntityType.PROMPT,
            "resource": EntityType.RESOURCE,
            "agent": EntityType.AGENT,
            "virtual_server": EntityType.VIRTUAL_SERVER,
            "mcp_server": EntityType.MCP_SERVER,
        }

        if entity_type not in type_map:
            raise ValueError(f"Invalid entity type: {entity_type}")

        return type_map[entity_type]
