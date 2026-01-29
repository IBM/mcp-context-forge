# -*- coding: utf-8 -*-
"""Extra schema validator tests to cover edge cases."""

# Standard
from types import SimpleNamespace

# Third-Party
import pytest
from pydantic import ValidationError

# First-Party
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.schemas import (
    GatewayCreate,
    PromptCreate,
    ResourceUpdate,
    ToolCreate,
    ToolUpdate,
)


def test_tool_create_display_name_and_auth_assembly():
    too_long = "x" * (SecurityValidator.MAX_NAME_LENGTH + 1)
    with pytest.raises(ValueError):
        ToolCreate.validate_display_name(too_long)

    values = {"auth_type": "basic", "auth_username": "user", "auth_password": "pass"}
    result = ToolCreate.assemble_auth(values)
    assert result["auth"]["auth_type"] == "basic"
    assert result["auth"]["auth_value"]

    values = {"auth_type": "authheaders"}
    result = ToolCreate.assemble_auth(values)
    assert result["auth"]["auth_type"] == "authheaders"
    assert result["auth"]["auth_value"] is None


def test_tool_create_prevent_manual_and_passthrough_rules():
    with pytest.raises(ValueError):
        ToolCreate.prevent_manual_mcp_creation({"integration_type": "MCP"})

    with pytest.raises(ValueError):
        ToolCreate.prevent_manual_mcp_creation({"integration_type": "A2A"})

    ToolCreate.prevent_manual_mcp_creation({"integration_type": "A2A", "allow_auto": True})

    with pytest.raises(ValueError):
        ToolCreate.enforce_passthrough_fields_for_rest({"integration_type": "MCP", "base_url": "http://example.com"})

    ToolCreate.enforce_passthrough_fields_for_rest({"integration_type": "REST", "base_url": "http://example.com"})


def test_tool_create_passthrough_validators():
    values = ToolCreate.extract_base_url_and_path_template({"integration_type": "REST", "url": "http://example.com/api"})
    assert values["base_url"] == "http://example.com"
    assert values["path_template"] == "/api"

    with pytest.raises(ValueError):
        ToolCreate.validate_base_url("example.com")

    with pytest.raises(ValueError):
        ToolCreate.validate_path_template("no-slash")

    with pytest.raises(ValueError):
        ToolCreate.validate_timeout_ms(0)

    with pytest.raises(ValueError):
        ToolCreate.validate_allowlist("not-a-list")

    with pytest.raises(ValueError):
        ToolCreate.validate_allowlist(["http://ok", 123])

    with pytest.raises(ValueError):
        ToolCreate.validate_allowlist(["not a host"])

    with pytest.raises(ValueError):
        ToolCreate.validate_plugin_chain(["unknown_plugin"])


def test_tool_request_type_validation_unknown_integration():
    info = SimpleNamespace(data={"integration_type": "UNKNOWN"})
    with pytest.raises(ValueError):
        ToolCreate.validate_request_type("POST", info)

    info = SimpleNamespace(data={"integration_type": "A2A"})
    with pytest.raises(ValueError):
        ToolCreate.validate_request_type("GET", info)


def test_tool_update_validators():
    too_long = "x" * (SecurityValidator.MAX_NAME_LENGTH + 1)
    with pytest.raises(ValueError):
        ToolUpdate.validate_display_name(too_long)

    with pytest.raises(ValueError):
        ToolUpdate.prevent_manual_mcp_update({"integration_type": "MCP"})

    with pytest.raises(ValueError):
        ToolUpdate.prevent_manual_mcp_update({"integration_type": "A2A"})


def test_resource_update_content_and_description():
    long_desc = "x" * (SecurityValidator.MAX_DESCRIPTION_LENGTH + 5)
    truncated = ResourceUpdate.validate_description(long_desc)
    assert len(truncated) == SecurityValidator.MAX_DESCRIPTION_LENGTH

    with pytest.raises(ValueError):
        ResourceUpdate.validate_content("x" * (SecurityValidator.MAX_CONTENT_LENGTH + 1))

    with pytest.raises(ValueError):
        ResourceUpdate.validate_content(b"\xff\xfe\xfd")

    with pytest.raises(ValueError):
        ResourceUpdate.validate_content("<script>alert(1)</script>")


def test_prompt_create_validators():
    ok = PromptCreate.validate_name("valid-prompt")
    assert ok == "valid-prompt"

    long_desc = "x" * (SecurityValidator.MAX_DESCRIPTION_LENGTH + 5)
    truncated = PromptCreate.validate_description(long_desc)
    assert len(truncated) == SecurityValidator.MAX_DESCRIPTION_LENGTH


def test_gateway_create_transport_and_auth():
    with pytest.raises(ValueError):
        GatewayCreate.validate_transport("INVALID")

    with pytest.raises(ValidationError):
        GatewayCreate(name="gw", url="http://example.com", auth_type="bearer")

    gateway = GatewayCreate(name="gw", url="http://example.com", auth_type="bearer", auth_token="token")
    assert gateway.auth_value is not None
