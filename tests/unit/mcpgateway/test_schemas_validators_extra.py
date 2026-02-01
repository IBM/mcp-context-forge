# -*- coding: utf-8 -*-
"""Extra schema validator tests to cover edge cases."""

# Standard
import base64
from types import SimpleNamespace

# Third-Party
import pytest
from pydantic import ValidationError

# First-Party
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import settings
from mcpgateway.schemas import (
    A2AAgentCreate,
    A2AAgentRead,
    A2AAgentUpdate,
    GatewayCreate,
    GatewayRead,
    GatewayUpdate,
    PromptCreate,
    ResourceUpdate,
    ToolCreate,
    ToolUpdate,
)
from mcpgateway.utils.services_auth import decode_auth, encode_auth


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


def test_gateway_create_authheaders_and_basic_variants():
    gateway = GatewayCreate(
        name="gw",
        url="http://example.com",
        auth_type="authheaders",
        auth_headers=[{"key": "X-API-Key", "value": "a"}, {"key": "X-API-Key", "value": "b"}],
    )
    decoded = decode_auth(gateway.auth_value)
    assert decoded["X-API-Key"] == "b"

    gateway = GatewayCreate(
        name="gw",
        url="http://example.com",
        auth_type="authheaders",
        auth_header_key="X-Token",
        auth_header_value="secret",
    )
    decoded = decode_auth(gateway.auth_value)
    assert decoded["X-Token"] == "secret"

    with pytest.raises(ValidationError):
        GatewayCreate(name="gw", url="http://example.com", auth_type="basic", auth_username="user")


def test_gateway_create_authheaders_validation_errors():
    with pytest.raises(ValidationError):
        GatewayCreate(
            name="gw",
            url="http://example.com",
            auth_type="authheaders",
            auth_headers=[{"key": "", "value": "x"}],
        )

    with pytest.raises(ValidationError):
        GatewayCreate(
            name="gw",
            url="http://example.com",
            auth_type="authheaders",
            auth_headers=[{"key": "Bad@Name", "value": "x"}],
        )

    too_many = [{"key": f"X-{i}", "value": "v"} for i in range(101)]
    with pytest.raises(ValidationError):
        GatewayCreate(name="gw", url="http://example.com", auth_type="authheaders", auth_headers=too_many)


def test_gateway_create_query_param_allowlist(monkeypatch):
    monkeypatch.setattr(settings, "insecure_allow_queryparam_auth", True)
    monkeypatch.setattr(settings, "insecure_queryparam_auth_allowed_hosts", ["allowed.example.com"])

    with pytest.raises(ValidationError):
        GatewayCreate(
            name="gw",
            url="http://denied.example.com",
            auth_type="query_param",
            auth_query_param_key="api_key",
            auth_query_param_value="secret",
        )

    gateway = GatewayCreate(
        name="gw",
        url="http://allowed.example.com",
        auth_type="query_param",
        auth_query_param_key="api_key",
        auth_query_param_value="secret",
    )
    assert gateway.auth_query_param_key == "api_key"


def test_gateway_create_query_param_disabled(monkeypatch):
    monkeypatch.setattr(settings, "insecure_allow_queryparam_auth", False)
    with pytest.raises(ValidationError):
        GatewayCreate(
            name="gw",
            url="http://example.com",
            auth_type="query_param",
            auth_query_param_key="api_key",
            auth_query_param_value="secret",
        )


def test_gateway_update_query_param_validation():
    with pytest.raises(ValidationError):
        GatewayUpdate(auth_type="query_param", auth_query_param_key="api_key")

    updated = GatewayUpdate(auth_type="query_param", auth_query_param_key="api_key", auth_query_param_value="secret")
    assert updated.auth_query_param_key == "api_key"


def test_gateway_read_mask_and_populate_auth():
    masked = GatewayRead._mask_query_param_auth({"auth_query_params": {"api_key": "enc"}})
    assert masked["auth_query_param_key"] == "api_key"
    assert masked["auth_query_param_value_masked"] == settings.masked_auth_value

    class DummyGateway:
        __table__ = SimpleNamespace(columns=[SimpleNamespace(name="id"), SimpleNamespace(name="auth_query_params")])

        def __init__(self):
            self.id = "gw1"
            self.auth_query_params = {"api_key": "enc"}
            self.team = "Team-1"

    masked_obj = GatewayRead._mask_query_param_auth(DummyGateway())
    assert masked_obj["auth_query_param_key"] == "api_key"
    assert masked_obj["team"] == "Team-1"

    encoded_basic = base64.urlsafe_b64encode("admin:secret".encode("utf-8")).decode("utf-8")
    basic = GatewayRead.model_construct(auth_type="basic", auth_value=encode_auth({"Authorization": f"Basic {encoded_basic}"}))
    basic = GatewayRead._populate_auth(basic)
    assert basic.auth_username == "admin"
    assert basic.auth_password == "secret"

    bearer = GatewayRead.model_construct(auth_type="bearer", auth_value=encode_auth({"Authorization": "Bearer token"}))
    bearer = GatewayRead._populate_auth(bearer)
    assert bearer.auth_token == "token"

    headers = GatewayRead.model_construct(auth_type="authheaders", auth_value=encode_auth({"X-Key": "val"}))
    headers = GatewayRead._populate_auth(headers)
    assert headers.auth_header_key == "X-Key"
    assert headers.auth_header_value == "val"

    masked_value = GatewayRead.model_construct(auth_type="basic", auth_value=settings.masked_auth_value)
    masked_value = GatewayRead._populate_auth(masked_value)
    assert masked_value.auth_username is None


def test_a2a_agent_auth_processing_and_read_masking(monkeypatch):
    agent = A2AAgentCreate(
        name="agent",
        endpoint_url="http://agent.example.com",
        auth_type="bearer",
        auth_token="token",
    )
    decoded = decode_auth(agent.auth_value)
    assert decoded["Authorization"] == "Bearer token"

    with pytest.raises(ValidationError):
        A2AAgentCreate(name="agent", endpoint_url="http://agent.example.com", auth_type="authheaders", auth_headers=[{"key": "", "value": "x"}])

    with pytest.raises(ValidationError):
        A2AAgentUpdate(auth_type="query_param", auth_query_param_key="key")

    monkeypatch.setattr(settings, "insecure_allow_queryparam_auth", True)
    monkeypatch.setattr(settings, "insecure_queryparam_auth_allowed_hosts", ["agent.example.com"])
    agent = A2AAgentCreate(
        name="agent",
        endpoint_url="http://agent.example.com",
        auth_type="query_param",
        auth_query_param_key="api_key",
        auth_query_param_value="secret",
    )
    assert agent.auth_query_param_key == "api_key"

    masked = A2AAgentRead._mask_query_param_auth({"auth_query_params": {"api_key": "enc"}})
    assert masked["auth_query_param_key"] == "api_key"

    encoded_basic = base64.urlsafe_b64encode("user:pass".encode("utf-8")).decode("utf-8")
    basic = A2AAgentRead.model_construct(auth_type="basic", auth_value=encode_auth({"Authorization": f"Basic {encoded_basic}"}))
    basic = A2AAgentRead._populate_auth(basic)
    assert basic.auth_username == "user"
    assert basic.auth_password == "pass"


def test_tool_update_auth_and_request_type():
    values = ToolUpdate.assemble_auth({"auth_type": "basic", "auth_username": "u", "auth_password": "p"})
    decoded = decode_auth(values["auth"]["auth_value"])
    assert decoded["Authorization"].startswith("Basic ")

    values = ToolUpdate.assemble_auth({"auth_type": "authheaders"})
    assert values["auth"]["auth_value"] is None

    info = SimpleNamespace(data={"integration_type": "A2A"})
    assert ToolUpdate.validate_request_type("POST", info) == "POST"
    with pytest.raises(ValueError):
        ToolUpdate.validate_request_type("GET", info)
