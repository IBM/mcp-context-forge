# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_tool_validation_policy.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the tool validation policy resolver.
"""

# Standard
import logging
from unittest.mock import MagicMock

# Third-Party
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.services import tool_validation_policy as policy_module
from mcpgateway.services.tool_validation_policy import SOURCE_GATEWAY, SOURCE_GLOBAL, SOURCE_NONE, SOURCE_TOOL, admit_tool, evaluate_tool_policy, global_policy_expression, resolve_policy
from mcpgateway.utils.cel_runner import CelError

DEFAULT_PATTERNS = ["&&", "||", "$("]


@pytest.fixture(autouse=True)
def strict_defaults(monkeypatch):
    """Run in-process, strict, with the shipped global pattern list."""
    monkeypatch.setattr(settings, "cel_execution", "inprocess")
    monkeypatch.setattr(settings, "validation_strict", True)
    monkeypatch.setattr(settings, "tool_description_forbidden_patterns_enabled", True)
    monkeypatch.setattr(settings, "tool_description_forbidden_patterns", list(DEFAULT_PATTERNS))


# --- global expression -------------------------------------------------------


def test_global_expression_from_default_patterns():
    """The shipped pattern list compiles to one negated contains-chain."""
    assert global_policy_expression() == '!(description.contains("&&") || description.contains("||") || description.contains("$("))'


def test_global_expression_skips_blank_patterns(monkeypatch):
    """Empty and whitespace-only entries are ignored, as the old loop ignored them."""
    monkeypatch.setattr(settings, "tool_description_forbidden_patterns", ["", "  ", "&&"])
    assert global_policy_expression() == '!(description.contains("&&"))'


def test_global_expression_none_when_disabled_or_empty(monkeypatch):
    """No global policy when the flag is off or nothing is listed."""
    monkeypatch.setattr(settings, "tool_description_forbidden_patterns", [])
    assert global_policy_expression() is None
    monkeypatch.setattr(settings, "tool_description_forbidden_patterns", ["&&"])
    monkeypatch.setattr(settings, "tool_description_forbidden_patterns_enabled", False)
    assert global_policy_expression() is None


def test_global_expression_quotes_special_characters(monkeypatch):
    """A pattern containing quotes or backslashes still matches literally."""
    monkeypatch.setattr(settings, "tool_description_forbidden_patterns", ['say "hi"', "a\\b"])
    assert evaluate_tool_policy(description='please say "hi"', tool_name="t").allowed is False
    assert evaluate_tool_policy(description="path a\\b here", tool_name="t").allowed is False
    assert evaluate_tool_policy(description="harmless", tool_name="t").allowed is True


# --- resolution order --------------------------------------------------------


def test_tool_policy_wins_over_gateway_and_global():
    """The most specific level decides."""
    assert resolve_policy("true", "false") == ("true", SOURCE_TOOL)


def test_blank_tool_policy_inherits_gateway():
    """Whitespace counts as empty."""
    assert resolve_policy("   ", " false ") == ("false", SOURCE_GATEWAY)


def test_empty_levels_fall_through_to_global():
    """With nothing stored, the global settings apply."""
    expression, source = resolve_policy(None, None)
    assert source == SOURCE_GLOBAL
    assert expression == global_policy_expression()


def test_non_text_values_are_treated_as_empty():
    """A column read through a mock or a wrong type never becomes a policy."""
    assert resolve_policy(MagicMock(), 42) == (global_policy_expression(), SOURCE_GLOBAL)


def test_non_text_description_and_name_count_as_empty():
    """Only text reaches the sandbox; anything else evaluates as an empty string."""
    decision = evaluate_tool_policy(description=MagicMock(), tool_name=42, gateway_policy='description == "" && tool_name == ""')
    assert decision.allowed is True


def test_no_policy_anywhere(monkeypatch):
    """Global disabled and no overrides means every tool is allowed."""
    monkeypatch.setattr(settings, "tool_description_forbidden_patterns_enabled", False)
    assert resolve_policy(None, None) == (None, SOURCE_NONE)
    decision = evaluate_tool_policy(description="rm -rf / && echo", tool_name="t")
    assert decision.allowed is True
    assert decision.source == SOURCE_NONE


def test_gateway_override_applies_even_when_global_disabled(monkeypatch):
    """The enabled flag governs the global default only."""
    monkeypatch.setattr(settings, "tool_description_forbidden_patterns_enabled", False)
    assert evaluate_tool_policy(description="x", tool_name="t", gateway_policy="false").allowed is False


# --- evaluation -------------------------------------------------------------


@pytest.mark.parametrize("pattern", DEFAULT_PATTERNS)
@pytest.mark.parametrize("position", ["start", "middle", "end"])
def test_default_patterns_are_denied_wherever_they_appear(pattern, position):
    """Each shipped pattern is refused at the start, middle, or end of a description."""
    description = {"start": f"{pattern} tail", "middle": f"head {pattern} tail", "end": f"head {pattern}"}[position]
    decision = evaluate_tool_policy(description=description, tool_name="t")
    assert decision.allowed is False
    assert decision.source == SOURCE_GLOBAL
    assert decision.reason == "denied by the global validation policy"


@pytest.mark.parametrize("description", ["A safe description", "", None, "Markdown: `code`; cmd | grep x; > quote"])
def test_descriptions_without_patterns_are_allowed(description):
    """Safe text, empty text, no text, and the Markdown the old loop allowed all pass."""
    assert evaluate_tool_policy(description=description, tool_name="t").allowed is True


def test_gateway_override_relaxes_the_global_rule():
    """A gateway policy replaces the global one entirely for its tools."""
    decision = evaluate_tool_policy(description="make && make test", tool_name="build", gateway_policy='!description.contains("$(")')
    assert decision.allowed is True
    assert decision.source == SOURCE_GATEWAY


def test_reason_names_each_level_without_repeating_the_word_tool():
    """The refusal text reads naturally at every level."""
    assert evaluate_tool_policy(description="x", tool_name="t", tool_policy="false").reason == "denied by the tool-level validation policy"
    assert evaluate_tool_policy(description="x", tool_name="t", gateway_policy="false").reason == "denied by the gateway-level validation policy"
    assert evaluate_tool_policy(description="a && b", tool_name="t").reason == "denied by the global validation policy"


def test_tool_override_can_branch_on_name():
    """A per-tool policy sees the tool name."""
    policy = 'tool_name == "run_query"'
    assert evaluate_tool_policy(description="x", tool_name="run_query", tool_policy=policy).allowed is True
    assert evaluate_tool_policy(description="x", tool_name="other", tool_policy=policy).allowed is False


def test_evaluation_failure_counts_as_denial(monkeypatch):
    """A sandbox failure never lets a tool through unchecked."""
    monkeypatch.setattr(policy_module, "evaluate_expression", MagicMock(side_effect=CelError("sandbox down")))
    decision = evaluate_tool_policy(description="x", tool_name="t", gateway_policy="true")
    assert decision.allowed is False
    assert decision.reason == "could not be checked against the gateway-level validation policy: sandbox down"


# --- admit_tool and the strict flag -----------------------------------------


def test_admit_returns_none_when_allowed(caplog):
    """An allowed tool produces no refusal and a debug line naming the level."""
    with caplog.at_level(logging.DEBUG, logger=policy_module.__name__):
        assert admit_tool(description="safe", tool_name="t", context="unit") is None
    assert "Tool validation policy (global) allowed tool 't' during unit" in caplog.text


def test_admit_refuses_in_strict_mode(caplog):
    """Strict mode returns the bare reason and logs which level decided."""
    with caplog.at_level(logging.INFO, logger=policy_module.__name__):
        refusal = admit_tool(description="a && b", tool_name="build", gateway_policy=None, context="unit")
    assert refusal == "denied by the global validation policy"
    assert "Tool validation policy (global) refused tool 'build' during unit" in caplog.text


def test_admit_warns_and_allows_when_not_strict(monkeypatch, caplog):
    """With VALIDATION_STRICT off a refused tool is logged once and stored."""
    monkeypatch.setattr(settings, "validation_strict", False)
    with caplog.at_level(logging.WARNING, logger=policy_module.__name__):
        assert admit_tool(description="a && b || c $(d)", tool_name="build", context="unit") is None
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert warnings[0].getMessage() == "Tool 'build' denied by the global validation policy (VALIDATION_STRICT=false, proceeding) during unit"
