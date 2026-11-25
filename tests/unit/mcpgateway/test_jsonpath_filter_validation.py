# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_jsonpath_filter_validation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

The jsonpath_filter field must be a CEL expression over ``response`` at write time.
"""

# Third-Party
from pydantic import ValidationError
import pytest

# First-Party
from mcpgateway.schemas import ToolCreate, ToolUpdate

NOT_CEL = ["user@example.com", "response.items["]
WRONG_VARIABLE = ["data.items", "env", "payload.total"]
JQ_ERA = ["$ENV", ".data.items[].id", "$.main", ".", ".a | .b"]


@pytest.mark.parametrize("expression", NOT_CEL + WRONG_VARIABLE)
def test_tool_create_rejects_a_filter_that_cannot_run(expression):
    """A filter that does not compile or names another variable never reaches the database."""
    with pytest.raises(ValidationError, match="not a valid CEL expression"):
        ToolCreate(name="probe", url="https://example.com/api", jsonpath_filter=expression)


@pytest.mark.parametrize("expression", NOT_CEL + WRONG_VARIABLE)
def test_tool_update_rejects_a_filter_that_cannot_run(expression):
    """The same check applies on update."""
    with pytest.raises(ValidationError, match="not a valid CEL expression"):
        ToolUpdate(jsonpath_filter=expression)


@pytest.mark.parametrize("expression", JQ_ERA)
def test_jq_and_jsonpath_filters_are_rejected_with_guidance(expression):
    """A filter from the jq era is named as such and the error says what to write instead."""
    with pytest.raises(ValidationError, match=r"jq or JSONPath filter, which is no longer supported; write a CEL expression over 'response'"):
        ToolCreate(name="probe", url="https://example.com/api", jsonpath_filter=expression)
    with pytest.raises(ValidationError, match="no longer supported"):
        ToolUpdate(jsonpath_filter=expression)


def test_unknown_variable_message_names_the_one_available():
    """The error tells the author what the response is called."""
    with pytest.raises(ValidationError, match=r"unknown variable\(s\) \['data'\]; available: \['response'\]"):
        ToolCreate(name="probe", url="https://example.com/api", jsonpath_filter="data.items")


@pytest.mark.parametrize(
    "expression",
    ["response.data.items.map(i, i.id)", "response.env.region", "response", 'response.items.filter(i, i.size > 1)', '{"n": response.total}'],
)
def test_legitimate_filter_is_accepted(expression):
    """Ordinary field-extraction and reshaping filters are stored as written."""
    tool = ToolCreate(name="probe", url="https://example.com/api", jsonpath_filter=expression)
    assert tool.jsonpath_filter == expression


def test_empty_filter_is_accepted():
    """The default empty filter means 'no filtering'."""
    assert ToolCreate(name="probe", url="https://example.com/api", jsonpath_filter="").jsonpath_filter == ""


def test_federated_peer_tool_with_a_bad_filter_is_dropped():
    """An upstream gateway cannot plant a filter that can never run via discovery."""
    # First-Party
    from mcpgateway.services.gateway_service import GatewayService

    service = GatewayService()
    tools = [
        {"name": "good_tool", "url": "https://example.com/a", "jsonpath_filter": "response.data"},
        {"name": "bad_tool", "url": "https://example.com/b", "jsonpath_filter": "$ENV"},
    ]
    valid, errors = service._validate_tools(tools)  # pylint: disable=protected-access

    assert [tool.name for tool in valid] == ["good_tool"]
    assert any("bad_tool" in err and "no longer supported" in err for err in errors)


def test_all_tools_rejected_reports_the_reason():
    """A peer whose tools all fail validation fails registration with a legible cause."""
    # First-Party
    from mcpgateway.services.gateway_service import GatewayService

    service = GatewayService()
    tools = [{"name": "bad_tool", "url": "https://example.com/b", "jsonpath_filter": "$ENV"}]

    with pytest.raises(Exception) as excinfo:
        service._validate_tools(tools)  # pylint: disable=protected-access

    assert "no longer supported; write a CEL expression over 'response'" in str(excinfo.value)
    assert "bad_tool" in str(excinfo.value)
