# -*- coding: utf-8 -*-
"""Tests for PluginHookRule validation."""

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework.models import EntityType, PluginAttachment, PluginHookRule


class TestPluginHookRuleValidation:
    """Test validation for PluginHookRule configuration."""

    def test_valid_tag_based_rule(self):
        """Test that a valid tag-based rule passes validation."""
        rule = PluginHookRule(
            entities=[EntityType.TOOL],
            tags=["customer", "pii"],
            plugins=[PluginAttachment(name="pii_filter", priority=10)],
        )
        assert rule.tags == ["customer", "pii"]
        assert len(rule.plugins) == 1

    def test_valid_name_based_rule(self):
        """Test that a valid name-based rule passes validation."""
        rule = PluginHookRule(
            entities=[EntityType.TOOL],
            name="create_customer",
            plugins=[PluginAttachment(name="audit_logger", priority=10)],
        )
        assert rule.name == "create_customer"

    def test_valid_when_expression_rule(self):
        """Test that a valid when expression rule passes validation."""
        rule = PluginHookRule(
            entities=[EntityType.RESOURCE],
            when="payload.uri.endswith('.env')",
            plugins=[PluginAttachment(name="secret_redactor", priority=10)],
        )
        assert rule.when == "payload.uri.endswith('.env')"

    def test_valid_http_level_rule(self):
        """Test that a valid HTTP-level rule (entities=None) passes validation."""
        rule = PluginHookRule(
            entities=None,
            when="payload.method == 'POST'",
            plugins=[PluginAttachment(name="rate_limiter", priority=10)],
        )
        assert rule.entities is None
        assert rule.when == "payload.method == 'POST'"

    def test_fail_empty_plugins_list(self):
        """Test that a rule with empty plugins list fails validation."""
        with pytest.raises(ValueError, match="must have at least one plugin"):
            PluginHookRule(
                entities=[EntityType.TOOL],
                tags=["customer"],
                plugins=[],  # Empty!
            )

    def test_global_rule_without_criteria(self):
        """Test that rule without any matching criteria is valid (global rule)."""
        # Global rules with no filters should match ALL entities and hooks
        rule = PluginHookRule(
            plugins=[PluginAttachment(name="rate_limiter", priority=10)],
        )
        assert rule.plugins[0].name == "rate_limiter"
        assert rule.entities is None
        assert rule.name is None
        assert rule.tags is None or rule.tags == []
        assert rule.when is None

    def test_fail_invalid_when_syntax(self):
        """Test that invalid 'when' expression syntax fails validation."""
        with pytest.raises(ValueError, match="Invalid 'when' expression syntax"):
            PluginHookRule(
                entities=[EntityType.TOOL],
                when="invalid syntax (((",  # Invalid Python syntax
                plugins=[PluginAttachment(name="audit_logger", priority=10)],
            )

    def test_complex_when_expression(self):
        """Test that complex 'when' expressions with logical operators validate."""
        rule = PluginHookRule(
            entities=[EntityType.TOOL],
            when='args.size > 1000 and contains(tags, "production")',
            plugins=[PluginAttachment(name="size_validator", priority=10)],
        )
        assert "and" in rule.when
        assert "contains" in rule.when

    def test_multiple_matching_criteria(self):
        """Test that a rule with multiple criteria (name + tags + when) validates."""
        rule = PluginHookRule(
            entities=[EntityType.TOOL],
            name="create_customer",
            tags=["customer"],
            when="args.email is not None",
            plugins=[PluginAttachment(name="validator", priority=10)],
        )
        assert rule.name == "create_customer"
        assert rule.tags == ["customer"]
        assert rule.when == "args.email is not None"

    def test_server_filtering_with_name(self):
        """Test that server filtering combined with name matching validates."""
        rule = PluginHookRule(
            entities=[EntityType.TOOL],
            name="process_payment",
            server_name="production-api",
            plugins=[PluginAttachment(name="fraud_detector", priority=5)],
        )
        assert rule.server_name == "production-api"
