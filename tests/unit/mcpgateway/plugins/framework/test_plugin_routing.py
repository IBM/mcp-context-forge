# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/test_plugin_routing.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Teryl Taylor

Unit tests for plugin routing framework components.
Tests policy evaluation and field selection.

Note: Plugin resolution is now tested in test_rule_based_routing.py
using the new RuleBasedResolver class.
"""

# Standard
import pytest

# First-Party
from mcpgateway.plugins.framework.models import (
    FieldSelection,
)
from mcpgateway.plugins.framework.routing import (
    EvaluationContext,
    FieldSelector,
    PolicyEvaluator,
)


class TestPolicyEvaluator:
    """Tests for PolicyEvaluator."""

    def test_simple_comparison(self):
        """Test simple comparison expressions."""
        evaluator = PolicyEvaluator()
        ctx = EvaluationContext(args={"size": 1500})

        assert evaluator.evaluate("args.size > 1000", ctx) is True
        assert evaluator.evaluate("args.size < 1000", ctx) is False
        assert evaluator.evaluate("args.size == 1500", ctx) is True

    def test_logical_operators(self):
        """Test logical operators (and, or, not)."""
        evaluator = PolicyEvaluator()
        ctx = EvaluationContext(
            args={"size": 1500, "type": "customer"},
            entity={"tags": ["production"]},
        )

        assert evaluator.evaluate("args.size > 1000 and args.type == \"customer\"", ctx) is True
        assert evaluator.evaluate("args.size < 1000 or args.type == \"customer\"", ctx) is True
        assert evaluator.evaluate("not args.size < 1000", ctx) is True

    def test_contains_function(self):
        """Test contains() function for list/string membership."""
        evaluator = PolicyEvaluator()
        ctx = EvaluationContext(
            tags=["production", "customer-facing"],
        )

        assert evaluator.evaluate('contains(entity.tags, "production")', ctx) is True
        assert evaluator.evaluate('contains(entity.tags, "staging")', ctx) is False

    def test_in_operator(self):
        """Test 'in' operator for membership."""
        evaluator = PolicyEvaluator()
        ctx = EvaluationContext(agent={"id": "agent1"})

        assert evaluator.evaluate('agent.id in ["agent1", "agent2"]', ctx) is True
        assert evaluator.evaluate('agent.id in ["agent3", "agent4"]', ctx) is False

    def test_field_existence(self):
        """Test checking field existence with 'in' operator."""
        evaluator = PolicyEvaluator()
        ctx = EvaluationContext(args={"user_query": "test", "limit": 10})

        assert evaluator.evaluate('"user_query" in args', ctx) is True
        assert evaluator.evaluate('"missing" in args', ctx) is False

    def test_empty_expression(self):
        """Test that empty expression returns True."""
        evaluator = PolicyEvaluator()
        ctx = EvaluationContext()

        assert evaluator.evaluate("", ctx) is True
        assert evaluator.evaluate("   ", ctx) is True

    def test_caching(self):
        """Test that expression parsing is cached."""
        evaluator = PolicyEvaluator()
        ctx = EvaluationContext(args={"count": 5})

        # First evaluation
        result1 = evaluator.evaluate("args.count > 3", ctx)

        # Second evaluation should use cache
        result2 = evaluator.evaluate("args.count > 3", ctx)

        assert result1 == result2 == True

        # Check cache info
        cache_info = evaluator._parse_expression.cache_info()
        assert cache_info.hits > 0


class TestFieldSelector:
    """Tests for FieldSelector."""

    def test_simple_field_extraction(self):
        """Test extracting a simple top-level field."""
        selector = FieldSelector()
        payload = {"args": {"query": "test", "limit": 10}}

        extracted = selector.extract_fields(payload, ["args.query"])

        assert extracted == {"args": {"query": "test"}}

    def test_nested_field_extraction(self):
        """Test extracting nested fields."""
        selector = FieldSelector()
        payload = {
            "args": {
                "filters": {"email": "john@example.com", "phone": "555-1234"},
                "limit": 10,
            }
        }

        extracted = selector.extract_fields(
            payload, ["args.filters.email", "args.filters.phone"]
        )

        assert extracted == {
            "args": {"filters": {"email": "john@example.com", "phone": "555-1234"}}
        }

    def test_array_wildcard_extraction(self):
        """Test extracting array elements with wildcard."""
        selector = FieldSelector()
        payload = {
            "args": {
                "customers": [
                    {"name": "Alice", "email": "alice@example.com"},
                    {"name": "Bob", "email": "bob@example.com"},
                ]
            }
        }

        extracted = selector.extract_fields(payload, ["args.customers[*].email"])

        assert extracted == {
            "args": {
                "customers": [
                    {"email": "alice@example.com"},
                    {"email": "bob@example.com"},
                ]
            }
        }

    def test_merge_fields(self):
        """Test merging processed fields back into original."""
        selector = FieldSelector()
        original = {"args": {"query": "sensitive", "limit": 10}}
        processed = {"args": {"query": "[REDACTED]"}}

        merged = selector.merge_fields(original, processed, ["args.query"])

        assert merged == {"args": {"query": "[REDACTED]", "limit": 10}}

    def test_apply_field_selection_input(self):
        """Test applying field selection for input (pre-hook)."""
        selector = FieldSelector()
        fs = FieldSelection(input_fields=["args.query"])
        payload = {"args": {"query": "test", "limit": 10}}

        filtered, paths = selector.apply_field_selection(payload, fs, is_input=True)

        assert filtered == {"args": {"query": "test"}}
        assert paths == ["args.query"]

    def test_apply_field_selection_output(self):
        """Test applying field selection for output (post-hook)."""
        selector = FieldSelector()
        fs = FieldSelection(output_fields=["result.ssn"])
        payload = {"result": {"ssn": "123-45-6789", "name": "John"}}

        filtered, paths = selector.apply_field_selection(payload, fs, is_input=False)

        assert filtered == {"result": {"ssn": "123-45-6789"}}
        assert paths == ["result.ssn"]

    def test_apply_field_selection_fallback_to_fields(self):
        """Test that fields is used when input_fields/output_fields not specified."""
        selector = FieldSelector()
        fs = FieldSelection(fields=["args.query"])
        payload = {"args": {"query": "test", "limit": 10}}

        # For input
        filtered_in, _ = selector.apply_field_selection(payload, fs, is_input=True)
        assert filtered_in == {"args": {"query": "test"}}

        # For output
        filtered_out, _ = selector.apply_field_selection(payload, fs, is_input=False)
        assert filtered_out == {"args": {"query": "test"}}

    def test_no_field_selection(self):
        """Test that None field selection returns original payload."""
        selector = FieldSelector()
        payload = {"args": {"query": "test", "limit": 10}}

        filtered, paths = selector.apply_field_selection(payload, None, is_input=True)

        assert filtered == payload
        assert paths is None

    def test_path_parsing(self):
        """Test path parsing with various notations."""
        selector = FieldSelector()

        assert selector._parse_path("args.query") == ["args", "query"]
        assert selector._parse_path("args.customers[0].email") == [
            "args",
            "customers[0]",
            "email",
        ]
        assert selector._parse_path("args.items[*].name") == [
            "args",
            "items[*]",
            "name",
        ]
