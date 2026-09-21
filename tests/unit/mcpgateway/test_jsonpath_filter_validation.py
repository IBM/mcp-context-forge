# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_jsonpath_filter_validation.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

The jsonpath_filter field must reject restricted jq built-ins at write time.
"""

# Third-Party
from pydantic import ValidationError
import pytest

# First-Party
from mcpgateway.schemas import ToolCreate, ToolUpdate

HOSTILE = ["$ENV", "env", '"\\(env)"', 'include "evil"; leak']


@pytest.mark.parametrize("jq_filter", HOSTILE)
def test_tool_create_rejects_hostile_filter(jq_filter):
    """A hostile filter never reaches the database through ToolCreate."""
    with pytest.raises(ValidationError, match="restricted"):
        ToolCreate(name="probe", url="https://example.com/api", jsonpath_filter=jq_filter)


@pytest.mark.parametrize("jq_filter", HOSTILE)
def test_tool_update_rejects_hostile_filter(jq_filter):
    """A hostile filter cannot be smuggled in through an update."""
    with pytest.raises(ValidationError, match="restricted"):
        ToolUpdate(jsonpath_filter=jq_filter)


def test_legitimate_filter_is_accepted():
    """Ordinary field-extraction filters keep working."""
    tool = ToolCreate(name="probe", url="https://example.com/api", jsonpath_filter=".data.items[].id")
    assert tool.jsonpath_filter == ".data.items[].id"


def test_env_named_field_is_accepted():
    """A field literally named 'env' is data access, not the built-in."""
    tool = ToolCreate(name="probe", url="https://example.com/api", jsonpath_filter=".env.region")
    assert tool.jsonpath_filter == ".env.region"


def test_empty_filter_is_accepted():
    """The default empty filter means 'no filtering'."""
    assert ToolCreate(name="probe", url="https://example.com/api", jsonpath_filter="").jsonpath_filter == ""


def test_federated_peer_tool_with_hostile_filter_is_dropped():
    """A malicious upstream gateway cannot plant a hostile filter via discovery."""
    # First-Party
    from mcpgateway.services.gateway_service import GatewayService

    service = GatewayService()
    tools = [
        {"name": "good_tool", "url": "https://example.com/a", "jsonpath_filter": ".data"},
        {"name": "evil_tool", "url": "https://example.com/b", "jsonpath_filter": "$ENV"},
    ]
    valid, errors = service._validate_tools(tools)  # pylint: disable=protected-access

    assert [tool.name for tool in valid] == ["good_tool"]
    assert any("evil_tool" in err and "restricted" in err for err in errors)


def test_all_tools_rejected_reports_the_reason():
    """A wholly hostile peer fails registration with a legible cause."""
    # First-Party
    from mcpgateway.services.gateway_service import GatewayService

    service = GatewayService()
    tools = [{"name": "evil_tool", "url": "https://example.com/b", "jsonpath_filter": "$ENV"}]

    with pytest.raises(Exception) as excinfo:
        service._validate_tools(tools)  # pylint: disable=protected-access

    assert "restricted" in str(excinfo.value)
    assert "evil_tool" in str(excinfo.value)
