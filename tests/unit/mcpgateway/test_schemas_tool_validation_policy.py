# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_schemas_tool_validation_policy.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for the tool_validation_policy field on the tool and gateway schemas.
"""

# Standard
import logging

# Third-Party
from pydantic import ValidationError
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.schemas import GatewayCreate, GatewayRead, GatewayUpdate, ToolCreate, ToolRead, ToolUpdate
from mcpgateway.utils.cel_runner import MAX_EXPRESSION_LENGTH

POLICY = '!description.contains("&&")'

WRITE_SCHEMAS = [
    pytest.param(ToolCreate, {"name": "list_files", "url": "http://example.com"}, id="ToolCreate"),
    pytest.param(ToolUpdate, {}, id="ToolUpdate"),
    pytest.param(GatewayCreate, {"name": "gw", "url": "http://example.com"}, id="GatewayCreate"),
    pytest.param(GatewayUpdate, {}, id="GatewayUpdate"),
]


@pytest.fixture(autouse=True)
def inprocess(monkeypatch):
    """Evaluate policies in the test process so schema tests need no sandbox."""
    monkeypatch.setattr(settings, "cel_execution", "inprocess")


@pytest.mark.parametrize("schema,base", WRITE_SCHEMAS)
def test_valid_policy_is_kept_and_stripped(schema, base):
    """A well-formed boolean expression is stored without surrounding whitespace."""
    assert schema(**base, tool_validation_policy=f"  {POLICY}  ").tool_validation_policy == POLICY


@pytest.mark.parametrize("schema,base", WRITE_SCHEMAS)
@pytest.mark.parametrize("empty", [None, "", "   "])
def test_empty_policy_becomes_none(schema, base, empty):
    """Empty text means inherit, which is stored as null."""
    assert schema(**base, tool_validation_policy=empty).tool_validation_policy is None


@pytest.mark.parametrize("schema,base", WRITE_SCHEMAS)
@pytest.mark.parametrize(
    "policy,fragment",
    [
        ('description.contains("&&"', "not a valid policy expression"),
        ('true || gatewy_id == "g1"', "unknown variable"),
        ("description", "expected bool"),
    ],
)
def test_broken_policy_is_rejected_on_save(schema, base, policy, fragment):
    """Syntax errors, unknown names, and non-boolean results are refused with a specific message."""
    with pytest.raises(ValidationError, match=fragment):
        schema(**base, tool_validation_policy=policy)


def test_rejected_policy_is_logged_with_its_reason(caplog):
    """An operator's broken expression leaves a trace in the log, not only in the response."""
    with caplog.at_level(logging.INFO, logger="mcpgateway.schemas"), pytest.raises(ValidationError):
        GatewayUpdate(tool_validation_policy="description")
    assert "Rejected tool_validation_policy 'description': expression returned str, expected bool" in caplog.text


@pytest.mark.parametrize("schema,base", WRITE_SCHEMAS)
def test_policy_over_length_cap_is_rejected(schema, base):
    """The schema enforces the evaluator's length cap before anything is evaluated."""
    with pytest.raises(ValidationError, match=f"at most {MAX_EXPRESSION_LENGTH} characters"):
        schema(**base, tool_validation_policy="true || " * (MAX_EXPRESSION_LENGTH // 8) + "true")


@pytest.mark.parametrize("schema", [ToolUpdate, GatewayUpdate])
def test_update_distinguishes_clear_from_unchanged(schema):
    """An explicit null clears the policy; leaving the field out leaves the stored value alone."""
    assert "tool_validation_policy" in schema(tool_validation_policy=None).model_fields_set
    assert "tool_validation_policy" in schema(tool_validation_policy="").model_fields_set
    assert "tool_validation_policy" not in schema().model_fields_set


@pytest.mark.parametrize("schema", [ToolRead, GatewayRead])
def test_read_schemas_expose_the_policy(schema):
    """The field is part of the read contract so API responses carry it."""
    assert "tool_validation_policy" in schema.model_fields
