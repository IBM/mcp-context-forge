# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/routing/test_rule_resolver.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Claude Code

Unit tests for RuleBasedResolver - flat rule-based plugin routing.
"""

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework import (
    EntityType,
    PluginAttachment,
    PluginHookRule,
    RuleBasedResolver,
    RuleMatchContext,
)


class TestRuleBasedResolver:
    """Test the RuleBasedResolver for flat rule-based routing."""

    def test_exact_name_match(self):
        """Test exact name matching (fast path)."""
        resolver = RuleBasedResolver()

        rules = [
            PluginHookRule(
                entities=[EntityType.TOOL],
                name="process_payment",
                plugins=[PluginAttachment(name="fraud_detector", priority=10)],
            )
        ]

        # Matching entity
        ctx = RuleMatchContext(
            name="process_payment",
            entity_type="tool",
        )
        attachments = resolver.resolve_for_entity(rules, ctx)
        assert len(attachments) == 1
        assert attachments[0].name == "fraud_detector"

        # Non-matching entity
        ctx2 = RuleMatchContext(
            name="create_user",
            entity_type="tool",
        )
        attachments2 = resolver.resolve_for_entity(rules, ctx2)
        assert len(attachments2) == 0

    def test_multiple_names_match(self):
        """Test matching multiple names in a rule."""
        resolver = RuleBasedResolver()

        rules = [
            PluginHookRule(
                entities=[EntityType.TOOL],
                name=["create_user", "update_user", "delete_user"],
                plugins=[PluginAttachment(name="user_validator", priority=10)],
            )
        ]

        # Match first name
        ctx1 = RuleMatchContext(name="create_user", entity_type="tool")
        attachments1 = resolver.resolve_for_entity(rules, ctx1)
        assert len(attachments1) == 1

        # Match second name
        ctx2 = RuleMatchContext(name="update_user", entity_type="tool")
        attachments2 = resolver.resolve_for_entity(rules, ctx2)
        assert len(attachments2) == 1

        # No match
        ctx3 = RuleMatchContext(name="get_user", entity_type="tool")
        attachments3 = resolver.resolve_for_entity(rules, ctx3)
        assert len(attachments3) == 0

    def test_tag_based_matching(self):
        """Test tag-based matching (fast path with set intersection)."""
        resolver = RuleBasedResolver()

        rules = [
            PluginHookRule(
                entities=[EntityType.TOOL],
                tags=["customer", "pii"],
                plugins=[
                    PluginAttachment(name="pii_filter", priority=10),
                    PluginAttachment(name="audit_logger", priority=20),
                ],
            )
        ]

        # Entity with matching tags
        ctx = RuleMatchContext(
            name="create_customer",
            entity_type="tool",
            tags=["customer", "pii", "write"],
        )
        attachments = resolver.resolve_for_entity(rules, ctx)
        assert len(attachments) == 2
        assert attachments[0].name == "pii_filter"
        assert attachments[1].name == "audit_logger"

        # Entity with partial tag match (should still match)
        ctx2 = RuleMatchContext(
            name="update_customer",
            entity_type="tool",
            tags=["customer"],  # Only one matching tag
        )
        attachments2 = resolver.resolve_for_entity(rules, ctx2)
        assert len(attachments2) == 2

        # Entity with no matching tags
        ctx3 = RuleMatchContext(
            name="get_product",
            entity_type="tool",
            tags=["product", "read"],
        )
        attachments3 = resolver.resolve_for_entity(rules, ctx3)
        assert len(attachments3) == 0

    def test_when_expression_matching(self):
        """Test when expression matching (flexible path)."""
        # First-Party
        from mcpgateway.plugins.framework.routing.evaluator import EvaluationContext

        resolver = RuleBasedResolver()

        rules = [
            PluginHookRule(
                entities=[EntityType.RESOURCE],
                when="payload.uri.endswith('.env') or payload.uri.endswith('.secrets')",
                plugins=[PluginAttachment(name="secret_redactor", priority=10)],
            )
        ]

        # Matching .env file
        ctx1 = RuleMatchContext(
            name="config.env",
            entity_type="resource",
            payload={"uri": "file:///app/.env"},
        )
        eval_ctx1 = EvaluationContext(
            name="config.env",
            entity_type="resource",
            payload={"uri": "file:///app/.env"},
        )
        attachments1 = resolver.resolve_for_entity(rules, ctx1, eval_context=eval_ctx1)
        assert len(attachments1) == 1
        assert attachments1[0].name == "secret_redactor"

        # Matching .secrets file
        ctx2 = RuleMatchContext(
            name="api.secrets",
            entity_type="resource",
            payload={"uri": "file:///app/api.secrets"},
        )
        eval_ctx2 = EvaluationContext(
            name="api.secrets",
            entity_type="resource",
            payload={"uri": "file:///app/api.secrets"},
        )
        attachments2 = resolver.resolve_for_entity(rules, ctx2, eval_context=eval_ctx2)
        assert len(attachments2) == 1

        # Non-matching file
        ctx3 = RuleMatchContext(
            name="data.txt",
            entity_type="resource",
            payload={"uri": "file:///app/data.txt"},
        )
        eval_ctx3 = EvaluationContext(
            name="data.txt",
            entity_type="resource",
            payload={"uri": "file:///app/data.txt"},
        )
        attachments3 = resolver.resolve_for_entity(rules, ctx3, eval_context=eval_ctx3)
        assert len(attachments3) == 0

    def test_combined_name_and_tags(self):
        """Test combining exact name AND tag matching."""
        resolver = RuleBasedResolver()

        rules = [
            PluginHookRule(
                entities=[EntityType.TOOL],
                name="process_payment",
                tags=["sensitive"],
                plugins=[PluginAttachment(name="enhanced_security", priority=10)],
            )
        ]

        # Both name and tags match
        ctx1 = RuleMatchContext(
            name="process_payment",
            entity_type="tool",
            tags=["sensitive", "financial"],
        )
        attachments1 = resolver.resolve_for_entity(rules, ctx1)
        assert len(attachments1) == 1

        # Name matches but tags don't
        ctx2 = RuleMatchContext(
            name="process_payment",
            entity_type="tool",
            tags=["normal"],
        )
        attachments2 = resolver.resolve_for_entity(rules, ctx2)
        assert len(attachments2) == 0

        # Tags match but name doesn't
        ctx3 = RuleMatchContext(
            name="other_tool",
            entity_type="tool",
            tags=["sensitive"],
        )
        attachments3 = resolver.resolve_for_entity(rules, ctx3)
        assert len(attachments3) == 0

    def test_server_filtering(self):
        """Test server_name and server_id filtering."""
        resolver = RuleBasedResolver()

        rules = [
            PluginHookRule(
                entities=[EntityType.TOOL],
                server_name="production-api",
                tags=["pii"],
                plugins=[PluginAttachment(name="prod_pii_filter", priority=10)],
            )
        ]

        # Server matches
        ctx1 = RuleMatchContext(
            name="get_customer",
            entity_type="tool",
            server_name="production-api",
            tags=["pii"],
        )
        attachments1 = resolver.resolve_for_entity(rules, ctx1)
        assert len(attachments1) == 1

        # Server doesn't match
        ctx2 = RuleMatchContext(
            name="get_customer",
            entity_type="tool",
            server_name="staging-api",
            tags=["pii"],
        )
        attachments2 = resolver.resolve_for_entity(rules, ctx2)
        assert len(attachments2) == 0

    def test_multiple_server_names(self):
        """Test filtering with multiple server names."""
        resolver = RuleBasedResolver()

        rules = [
            PluginHookRule(
                entities=[EntityType.TOOL],
                server_name=["production-api", "staging-api"],
                plugins=[PluginAttachment(name="monitor", priority=10)],
            )
        ]

        # First server matches
        ctx1 = RuleMatchContext(
            name="tool1",
            entity_type="tool",
            server_name="production-api",
        )
        attachments1 = resolver.resolve_for_entity(rules, ctx1)
        assert len(attachments1) == 1

        # Second server matches
        ctx2 = RuleMatchContext(
            name="tool1",
            entity_type="tool",
            server_name="staging-api",
        )
        attachments2 = resolver.resolve_for_entity(rules, ctx2)
        assert len(attachments2) == 1

        # Different server doesn't match
        ctx3 = RuleMatchContext(
            name="tool1",
            entity_type="tool",
            server_name="dev-api",
        )
        attachments3 = resolver.resolve_for_entity(rules, ctx3)
        assert len(attachments3) == 0

    def test_gateway_filtering(self):
        """Test gateway_id filtering."""
        resolver = RuleBasedResolver()

        rules = [
            PluginHookRule(
                entities=[EntityType.TOOL],
                gateway_id="gateway-us-east",
                plugins=[PluginAttachment(name="us_compliance", priority=10)],
            )
        ]

        # Gateway matches
        ctx1 = RuleMatchContext(
            name="tool1",
            entity_type="tool",
            gateway_id="gateway-us-east",
        )
        attachments1 = resolver.resolve_for_entity(rules, ctx1)
        assert len(attachments1) == 1

        # Gateway doesn't match
        ctx2 = RuleMatchContext(
            name="tool1",
            entity_type="tool",
            gateway_id="gateway-eu-west",
        )
        attachments2 = resolver.resolve_for_entity(rules, ctx2)
        assert len(attachments2) == 0

    def test_entity_type_filtering(self):
        """Test that rules only apply to specified entity types."""
        resolver = RuleBasedResolver()

        rules = [
            PluginHookRule(
                entities=[EntityType.TOOL],
                tags=["customer"],
                plugins=[PluginAttachment(name="tool_plugin", priority=10)],
            )
        ]

        # Tool entity with matching tags
        ctx1 = RuleMatchContext(
            name="entity1",
            entity_type="tool",
            tags=["customer"],
        )
        attachments1 = resolver.resolve_for_entity(rules, ctx1)
        assert len(attachments1) == 1

        # Prompt entity with matching tags (shouldn't match - wrong entity type)
        ctx2 = RuleMatchContext(
            name="entity2",
            entity_type="prompt",
            tags=["customer"],
        )
        attachments2 = resolver.resolve_for_entity(rules, ctx2)
        assert len(attachments2) == 0

    def test_http_level_rules(self):
        """Test HTTP-level rules (no entities specified)."""
        # First-Party
        from mcpgateway.plugins.framework.routing.evaluator import EvaluationContext

        resolver = RuleBasedResolver()

        rules = [
            PluginHookRule(
                entities=None,  # HTTP-level
                when="payload.method == 'POST'",
                plugins=[PluginAttachment(name="rate_limiter", priority=10)],
            )
        ]

        # HTTP POST request
        ctx1 = RuleMatchContext(
            name="http_request",
            entity_type="http",
            payload={"method": "POST", "path": "/api/users"},
        )
        eval_ctx1 = EvaluationContext(
            name="http_request",
            entity_type="http",
            payload={"method": "POST", "path": "/api/users"},
        )
        attachments1 = resolver.resolve_for_entity(rules, ctx1, eval_context=eval_ctx1)
        assert len(attachments1) == 1

        # HTTP GET request
        ctx2 = RuleMatchContext(
            name="http_request",
            entity_type="http",
            payload={"method": "GET", "path": "/api/users"},
        )
        eval_ctx2 = EvaluationContext(
            name="http_request",
            entity_type="http",
            payload={"method": "GET", "path": "/api/users"},
        )
        attachments2 = resolver.resolve_for_entity(rules, ctx2, eval_context=eval_ctx2)
        assert len(attachments2) == 0

    def test_rule_priority_ordering(self):
        """Test that explicit rule priorities control order."""
        resolver = RuleBasedResolver()

        rules = [
            PluginHookRule(
                entities=[EntityType.TOOL],
                tags=["api"],
                priority=20,  # Lower priority (runs later)
                plugins=[PluginAttachment(name="general_validator", priority=10)],
            ),
            PluginHookRule(
                entities=[EntityType.TOOL],
                tags=["critical"],
                priority=10,  # Higher priority (runs first)
                plugins=[PluginAttachment(name="critical_check", priority=5)],
            ),
        ]

        # Entity matching both rules
        ctx = RuleMatchContext(
            name="important_tool",
            entity_type="tool",
            tags=["api", "critical"],
        )
        attachments = resolver.resolve_for_entity(rules, ctx)

        # Should have both plugins, critical_check first (lower priority value)
        assert len(attachments) == 2
        assert attachments[0].name == "critical_check"
        assert attachments[1].name == "general_validator"

    def test_specificity_based_ordering(self):
        """Test that specificity determines order when using merge_all strategy."""
        resolver = RuleBasedResolver()

        rules = [
            # Less specific (tag match only)
            PluginHookRule(
                entities=[EntityType.TOOL],
                tags=["customer"],
                plugins=[PluginAttachment(name="tag_plugin", priority=20)],
            ),
            # More specific (exact name match)
            PluginHookRule(
                entities=[EntityType.TOOL],
                name="create_customer",
                plugins=[PluginAttachment(name="name_plugin", priority=10)],
            ),
        ]

        ctx = RuleMatchContext(
            name="create_customer",
            entity_type="tool",
            tags=["customer"],
        )
        # Use merge_all to combine plugins from all matching rules
        attachments = resolver.resolve_for_entity(rules, ctx, merge_strategy="merge_all")

        # Should apply both, with name_plugin first (more specific rule)
        assert len(attachments) == 2
        assert attachments[0].name == "name_plugin"
        assert attachments[1].name == "tag_plugin"

    def test_plugin_priority_within_rule(self):
        """Test that plugins within a rule are sorted by their priority."""
        resolver = RuleBasedResolver()

        rules = [
            PluginHookRule(
                entities=[EntityType.TOOL],
                name="test_tool",
                plugins=[
                    PluginAttachment(name="plugin_c", priority=30),
                    PluginAttachment(name="plugin_a", priority=10),
                    PluginAttachment(name="plugin_b", priority=20),
                ],
            )
        ]

        ctx = RuleMatchContext(name="test_tool", entity_type="tool")
        attachments = resolver.resolve_for_entity(rules, ctx)

        # Should be sorted by priority
        assert len(attachments) == 3
        assert attachments[0].name == "plugin_a"  # priority 10
        assert attachments[1].name == "plugin_b"  # priority 20
        assert attachments[2].name == "plugin_c"  # priority 30

    def test_duplicate_plugin_warning(self, caplog):
        """Test that most specific rule wins when same plugin appears in multiple rules."""
        resolver = RuleBasedResolver()

        rules = [
            PluginHookRule(
                entities=[EntityType.TOOL],
                tags=["customer"],
                plugins=[PluginAttachment(name="audit_logger", priority=10)],
            ),
            PluginHookRule(
                entities=[EntityType.TOOL],
                name="create_customer",
                plugins=[PluginAttachment(name="audit_logger", priority=20)],
            ),
        ]

        ctx = RuleMatchContext(
            name="create_customer",
            entity_type="tool",
            tags=["customer"],
        )

        attachments = resolver.resolve_for_entity(rules, ctx)

        # With default "most_specific" strategy, only the more specific rule (name match) is used
        assert len(attachments) == 1
        assert attachments[0].name == "audit_logger"
        assert attachments[0].priority == 20  # More specific rule (name match) wins over tag match

    def test_empty_rules_list(self):
        """Test that empty rules list returns no attachments."""
        resolver = RuleBasedResolver()

        ctx = RuleMatchContext(name="test", entity_type="tool")
        attachments = resolver.resolve_for_entity([], ctx)

        assert len(attachments) == 0

    def test_global_rule_matches_all_entities(self):
        """Test that a rule with no filtering criteria matches ALL entities (global rule)."""
        resolver = RuleBasedResolver()

        # Create a global rule with no filters - should apply everywhere
        rules = [
            PluginHookRule(
                # No entities, no name, no tags, no when, no server filters
                plugins=[
                    PluginAttachment(name="global_logger", priority=10),
                    PluginAttachment(name="global_metrics", priority=20),
                ],
            )
        ]

        # Test 1: Should match any tool
        ctx1 = RuleMatchContext(name="create_user", entity_type="tool", tags=["customer"])
        attachments1 = resolver.resolve_for_entity(rules, ctx1)
        assert len(attachments1) == 2
        assert attachments1[0].name == "global_logger"
        assert attachments1[1].name == "global_metrics"

        # Test 2: Should match any prompt
        ctx2 = RuleMatchContext(name="get_weather", entity_type="prompt", tags=["weather"])
        attachments2 = resolver.resolve_for_entity(rules, ctx2)
        assert len(attachments2) == 2
        assert attachments2[0].name == "global_logger"

        # Test 3: Should match any resource
        ctx3 = RuleMatchContext(name="config.json", entity_type="resource")
        attachments3 = resolver.resolve_for_entity(rules, ctx3)
        assert len(attachments3) == 2

        # Test 4: Should match HTTP-level requests
        ctx4 = RuleMatchContext(name="http_request", entity_type="http", payload={"method": "POST"})
        attachments4 = resolver.resolve_for_entity(rules, ctx4)
        assert len(attachments4) == 2

        # Test 5: Should match entities with no tags
        ctx5 = RuleMatchContext(name="simple_tool", entity_type="tool")
        attachments5 = resolver.resolve_for_entity(rules, ctx5)
        assert len(attachments5) == 2

        # Test 6: Should match even when server context is present
        ctx6 = RuleMatchContext(
            name="server_tool",
            entity_type="tool",
            server_name="production-api",
            gateway_id="gateway-1",
        )
        attachments6 = resolver.resolve_for_entity(rules, ctx6)
        assert len(attachments6) == 2

    def test_global_rule_combined_with_specific_rules(self):
        """Test that global rules combine correctly with more specific rules."""
        resolver = RuleBasedResolver()

        rules = [
            # Global rule - applies to everything
            PluginHookRule(
                plugins=[PluginAttachment(name="global_logger", priority=100)],
            ),
            # Specific rule for tools with "customer" tag
            PluginHookRule(
                entities=[EntityType.TOOL],
                tags=["customer"],
                plugins=[PluginAttachment(name="pii_filter", priority=10)],
            ),
        ]

        # Test 1: Entity matching the specific rule should get both plugins (using merge_all)
        ctx1 = RuleMatchContext(name="create_customer", entity_type="tool", tags=["customer"])
        attachments1 = resolver.resolve_for_entity(rules, ctx1, merge_strategy="merge_all")
        assert len(attachments1) == 2
        # More specific rule (tag match) should come first
        assert attachments1[0].name == "pii_filter"
        assert attachments1[1].name == "global_logger"

        # Test 2: Entity NOT matching specific rule should only get global plugin
        ctx2 = RuleMatchContext(name="get_product", entity_type="tool", tags=["product"])
        attachments2 = resolver.resolve_for_entity(rules, ctx2)
        assert len(attachments2) == 1
        assert attachments2[0].name == "global_logger"

        # Test 3: Different entity type should only get global plugin
        ctx3 = RuleMatchContext(name="weather_prompt", entity_type="prompt")
        attachments3 = resolver.resolve_for_entity(rules, ctx3)
        assert len(attachments3) == 1
        assert attachments3[0].name == "global_logger"

    def test_no_matching_rules(self):
        """Test that non-matching rules return no attachments."""
        resolver = RuleBasedResolver()

        rules = [
            PluginHookRule(
                entities=[EntityType.TOOL],
                name="other_tool",
                plugins=[PluginAttachment(name="plugin1", priority=10)],
            )
        ]

        ctx = RuleMatchContext(name="my_tool", entity_type="tool")
        attachments = resolver.resolve_for_entity(rules, ctx)

        assert len(attachments) == 0

    def test_payload_args_convenience_accessor(self):
        """Test that args are extracted from payload for convenience."""
        # First-Party
        from mcpgateway.plugins.framework.routing.evaluator import EvaluationContext

        resolver = RuleBasedResolver()

        rules = [
            PluginHookRule(
                entities=[EntityType.TOOL],
                when="args.size > 1000",
                plugins=[PluginAttachment(name="size_validator", priority=10)],
            )
        ]

        # Args in payload
        ctx = RuleMatchContext(
            name="test_tool",
            entity_type="tool",
            payload={"args": {"size": 1500}},
        )
        eval_ctx = EvaluationContext(
            name="test_tool",
            entity_type="tool",
            args={"size": 1500},
            payload={"args": {"size": 1500}},
        )
        attachments = resolver.resolve_for_entity(rules, ctx, eval_context=eval_ctx)
        assert len(attachments) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
