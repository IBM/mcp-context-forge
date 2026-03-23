# -*- coding: utf-8 -*-
"""Extra schema validator tests to cover edge cases."""

# Standard
import base64
from datetime import datetime, timezone
import json
import logging
from types import SimpleNamespace

# Third-Party
from pydantic import SecretStr, ValidationError
import pytest

# First-Party
from mcpgateway.common.models import ResourceContent
from mcpgateway.common.validators import SecurityValidator
from mcpgateway.config import settings
from mcpgateway.schemas import (
    _coerce_visibility,
    _mask_oauth_config,
    A2AAgentCreate,
    A2AAgentInvocation,
    A2AAgentRead,
    A2AAgentUpdate,
    AdminToolCreate,
    ChangePasswordRequest,
    EventMessage,
    GatewayCreate,
    GatewayRead,
    GatewayUpdate,
    GrpcServiceCreate,
    GrpcServiceRead,
    GrpcServiceUpdate,
    PromptCreate,
    PromptRead,
    PromptUpdate,
    ResourceCreate,
    ResourceNotification,
    ResourceRead,
    ResourceUpdate,
    RPCRequest,
    ServerCreate,
    ServerRead,
    ServerUpdate,
    TeamCreateRequest,
    TeamUpdateRequest,
    TokenScopeRequest,
    ToolCreate,
    ToolRead,
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


class TestToolUpdateDescriptionValidationStrict:
    """Tests for ToolUpdate.validate_description forbidden-pattern check.

    Mirrors TestToolCreateDescriptionValidationStrict to ensure ToolUpdate
    respects VALIDATION_STRICT the same way ToolCreate does.
    """

    def test_forbidden_pattern_rejected_in_strict_mode(self, monkeypatch):
        """Descriptions with shell/pipe metacharacters raise ValueError when VALIDATION_STRICT=true."""
        monkeypatch.setattr(settings, "validation_strict", True)
        for pat in ["&&", ";", "||", "$(", "|", "> ", "< "]:
            with pytest.raises(ValueError, match="unsafe characters"):
                ToolUpdate.validate_description(f"Valid prefix {pat} suffix")

    @pytest.mark.parametrize(
        "description",
        [
            "run cmd1 && cmd2",
            "end statement;",
            "try this || that",
            "expand $(cmd)",
            "pipe | grep",
            "Search docs > results",
            "read < file",
        ],
        ids=["ampersand", "semicolon", "or", "subshell", "pipe", "redirect_out", "redirect_in"],
    )
    def test_forbidden_pattern_allowed_in_non_strict_mode(self, monkeypatch, caplog, description):
        """Each forbidden pattern is accepted (with warning) when VALIDATION_STRICT=false."""
        monkeypatch.setattr(settings, "validation_strict", False)

        with caplog.at_level(logging.WARNING, logger="mcpgateway.schemas"):
            result = ToolUpdate.validate_description(description)
        assert result is not None
        assert any("potentially unsafe" in rec.message for rec in caplog.records)

    def test_non_strict_logs_single_warning_for_multiple_patterns(self, monkeypatch, caplog):
        """Only one warning is logged even when a description matches multiple forbidden patterns."""
        monkeypatch.setattr(settings, "validation_strict", False)

        with caplog.at_level(logging.WARNING, logger="mcpgateway.schemas"):
            result = ToolUpdate.validate_description("foo && bar | baz > qux")
        assert result is not None
        unsafe_warnings = [r for r in caplog.records if "potentially unsafe" in r.message]
        assert len(unsafe_warnings) == 1

    def test_safe_description_always_accepted(self, monkeypatch):
        """Safe descriptions pass in both strict and non-strict modes."""
        for strict in (True, False):
            monkeypatch.setattr(settings, "validation_strict", strict)
            result = ToolUpdate.validate_description("A perfectly safe description.")
            assert result == "A perfectly safe description."

    def test_none_description_always_accepted(self, monkeypatch):
        """None descriptions pass through unchanged in both modes."""
        for strict in (True, False):
            monkeypatch.setattr(settings, "validation_strict", strict)
            assert ToolUpdate.validate_description(None) is None

    def test_forbidden_patterns_match_tool_create(self, monkeypatch):
        """Ensure ToolCreate and ToolUpdate reject the exact same set of forbidden patterns in strict mode."""
        monkeypatch.setattr(settings, "validation_strict", True)
        forbidden_patterns = ["&&", ";", "||", "$(", "|", "> ", "< "]
        for pat in forbidden_patterns:
            payload = f"test {pat} injection"
            with pytest.raises(ValueError, match="unsafe characters"):
                ToolCreate.validate_description(payload)
            with pytest.raises(ValueError, match="unsafe characters"):
                ToolUpdate.validate_description(payload)

    def test_empty_string_accepted(self):
        """Empty string is a valid description (not None, not forbidden)."""
        assert ToolUpdate.validate_description("") == ""

    def test_forbidden_pattern_at_start(self, monkeypatch):
        """Forbidden pattern at the very start of a description is still caught."""
        monkeypatch.setattr(settings, "validation_strict", True)
        with pytest.raises(ValueError, match="unsafe characters"):
            ToolUpdate.validate_description("&&rest of description")

    def test_forbidden_pattern_at_end(self, monkeypatch):
        """Forbidden pattern at the very end of a description is still caught."""
        monkeypatch.setattr(settings, "validation_strict", True)
        with pytest.raises(ValueError, match="unsafe characters"):
            ToolUpdate.validate_description("description ends with ||")

    def test_exact_max_length_not_truncated(self):
        """Description exactly at MAX_DESCRIPTION_LENGTH is accepted without truncation."""
        exact = "x" * SecurityValidator.MAX_DESCRIPTION_LENGTH
        result = ToolUpdate.validate_description(exact)
        assert len(result) == SecurityValidator.MAX_DESCRIPTION_LENGTH


def test_resource_update_content_and_description():
    long_desc = "x" * (SecurityValidator.MAX_DESCRIPTION_LENGTH + 5)
    truncated = ResourceUpdate.validate_description(long_desc)
    assert len(truncated) == SecurityValidator.MAX_DESCRIPTION_LENGTH

    # Size validation is now done at service layer, not schema layer
    # Schema layer only validates encoding and dangerous patterns

    # Test UTF-8 encoding validation
    with pytest.raises(ValueError):
        ResourceUpdate.validate_content(b"\xff\xfe\xfd")

    # Test dangerous HTML pattern detection
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


def test_tool_create_optional_none_branches():
    assert ToolCreate.validate_url(None) is None
    assert ToolCreate.validate_base_url(None) is None
    assert ToolCreate.validate_allowlist(None) is None


def test_tool_update_more_branches(caplog):
    assert ToolUpdate.validate_url(None) is None

    caplog.set_level("INFO", logger="mcpgateway.schemas")
    long_desc = "x" * (SecurityValidator.MAX_DESCRIPTION_LENGTH + 1)
    truncated = ToolUpdate.validate_description(long_desc)
    assert len(truncated) == SecurityValidator.MAX_DESCRIPTION_LENGTH
    assert any("Description too long" in rec.message for rec in caplog.records)

    assert ToolUpdate.extract_base_url_and_path_template({"integration_type": "REST", "url": "example.com/api"})["path_template"].startswith("/")

    assert ToolUpdate.validate_base_url(None) is None
    with pytest.raises(ValueError):
        ToolUpdate.validate_base_url("example.com")

    assert ToolUpdate.validate_timeout_ms(None) is None
    assert ToolUpdate.validate_timeout_ms(10) == 10

    assert ToolUpdate.validate_allowlist(["example.com:443", "https://example.com"]) == ["example.com:443", "https://example.com"]
    assert ToolUpdate.validate_plugin_chain(["deny_filter", "rate_limit"]) == ["deny_filter", "rate_limit"]

    assert ToolUpdate.validate_request_type("SSE", SimpleNamespace(data={"integration_type": "MCP"})) == "SSE"
    with pytest.raises(ValueError):
        ToolUpdate.validate_request_type("POST", SimpleNamespace(data={"integration_type": "UNKNOWN"}))

    bearer = ToolUpdate.assemble_auth({"auth_type": "bearer", "auth_token": "tok"})
    assert decode_auth(bearer["auth"]["auth_value"])["Authorization"] == "Bearer tok"

    hdrs = ToolUpdate.assemble_auth({"auth_type": "authheaders", "auth_header_key": "X-Key", "auth_header_value": "val"})
    assert decode_auth(hdrs["auth"]["auth_value"])["X-Key"] == "val"


def test_resource_create_and_notifications_serialization():
    assert ResourceCreate.validate_content(None) is None

    fixed = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    notif = ResourceNotification(
        uri="file:///resource",
        content=ResourceContent(type="resource", id="r1", uri="file:///resource"),
        timestamp=fixed,
    )
    dumped = json.loads(notif.model_dump_json())
    assert dumped["timestamp"].endswith("Z")


def test_prompt_update_description_truncation(caplog):
    caplog.set_level("INFO", logger="mcpgateway.schemas")
    long_desc = "x" * (SecurityValidator.MAX_DESCRIPTION_LENGTH + 1)
    truncated = PromptUpdate.validate_description(long_desc)
    assert len(truncated) == SecurityValidator.MAX_DESCRIPTION_LENGTH
    assert any("Description too long" in rec.message for rec in caplog.records)


def test_gateway_create_more_branches(monkeypatch):
    long_desc = "x" * (SecurityValidator.MAX_DESCRIPTION_LENGTH + 1)
    assert len(GatewayCreate.validate_description(long_desc)) == SecurityValidator.MAX_DESCRIPTION_LENGTH

    # Covers auth_type == one_time_auth in _process_auth_fields
    gw = GatewayCreate(name="gw", url="http://example.com", auth_type="one_time_auth")
    assert gw.auth_value is None

    # Covers invalid auth_type in _process_auth_fields
    with pytest.raises((ValidationError, ValueError)):
        GatewayCreate(name="gw", url="http://example.com", auth_type="invalid")

    # Covers skipping non-dict elements in auth_headers parsing
    auth_value = GatewayCreate._process_auth_fields(SimpleNamespace(data={"auth_type": "authheaders", "auth_headers": ["nope", {"key": "X-Key", "value": "v"}]}))
    assert decode_auth(auth_value)["X-Key"] == "v"

    # Covers query_param required fields in validate_query_param_auth
    monkeypatch.setattr(settings, "insecure_allow_queryparam_auth", True)
    monkeypatch.setattr(settings, "insecure_queryparam_auth_allowed_hosts", [])
    with pytest.raises((ValidationError, ValueError)):
        GatewayCreate(name="gw", url="http://example.com", auth_type="query_param", auth_query_param_value=SecretStr("secret"))
    with pytest.raises((ValidationError, ValueError)):
        GatewayCreate(name="gw", url="http://example.com", auth_type="query_param", auth_query_param_key="api_key")


def test_gateway_update_more_branches(caplog):
    caplog.set_level("WARNING", logger="mcpgateway.schemas")
    long_desc = "x" * (SecurityValidator.MAX_DESCRIPTION_LENGTH + 1)
    assert len(GatewayUpdate.validate_description(long_desc)) == SecurityValidator.MAX_DESCRIPTION_LENGTH

    # basic auth missing password
    with pytest.raises(ValueError):
        GatewayUpdate._process_auth_fields(SimpleNamespace(data={"auth_type": "basic", "auth_username": "u"}))

    # authheaders: skip non-dict, skip missing key, warn duplicates, and return encoded headers
    encoded = GatewayUpdate._process_auth_fields(
        SimpleNamespace(
            data={
                "auth_type": "authheaders",
                "auth_headers": ["nope", {"key": "", "value": "x"}, {"key": "X-Token", "value": "a"}, {"key": "X-Token", "value": "b"}],
            }
        )
    )
    assert decode_auth(encoded)["X-Token"] == "b"
    assert any("Duplicate header keys detected" in rec.message for rec in caplog.records)

    # invalid header key
    with pytest.raises(ValueError):
        GatewayUpdate._process_auth_fields(SimpleNamespace(data={"auth_type": "authheaders", "auth_headers": [{"key": "Bad:Key", "value": "v"}]}))

    # no valid header key
    with pytest.raises(ValueError):
        GatewayUpdate._process_auth_fields(SimpleNamespace(data={"auth_type": "authheaders", "auth_headers": [{"key": "", "value": "v"}]}))

    # too many headers
    too_many = [{"key": f"X-{i}", "value": "v"} for i in range(101)]
    with pytest.raises(ValueError):
        GatewayUpdate._process_auth_fields(SimpleNamespace(data={"auth_type": "authheaders", "auth_headers": too_many}))

    # legacy headers missing key/value
    with pytest.raises(ValueError):
        GatewayUpdate._process_auth_fields(SimpleNamespace(data={"auth_type": "authheaders"}))

    assert GatewayUpdate._process_auth_fields(SimpleNamespace(data={"auth_type": "one_time_auth"})) is None
    with pytest.raises(ValueError):
        GatewayUpdate._process_auth_fields(SimpleNamespace(data={"auth_type": "invalid"}))

    with pytest.raises((ValidationError, ValueError)):
        GatewayUpdate(auth_type="query_param", auth_query_param_value=SecretStr("secret"))


def test_gateway_read_populate_auth_more_error_and_early_returns():
    one_time = GatewayRead.model_construct(auth_type="one_time_auth", auth_value=None)
    assert GatewayRead._populate_auth(one_time) is one_time

    qp = GatewayRead.model_construct(auth_type="query_param", auth_value=None)
    assert GatewayRead._populate_auth(qp) is qp

    bad_basic = GatewayRead.model_construct(auth_type="basic", auth_value=encode_auth({"Authorization": "Bearer token"}))
    with pytest.raises(ValueError):
        GatewayRead._populate_auth(bad_basic)

    encoded_user_only = base64.urlsafe_b64encode("user:".encode("utf-8")).decode("utf-8")
    missing_pw = GatewayRead.model_construct(auth_type="basic", auth_value=encode_auth({"Authorization": f"Basic {encoded_user_only}"}))
    with pytest.raises(ValueError):
        GatewayRead._populate_auth(missing_pw)

    bad_bearer = GatewayRead.model_construct(auth_type="bearer", auth_value=encode_auth({"Authorization": f"Basic {encoded_user_only}"}))
    with pytest.raises(ValueError):
        GatewayRead._populate_auth(bad_bearer)

    class TruthyDict(dict):
        def __bool__(self) -> bool:  # pragma: no cover - deterministic helper
            return True

    empty_headers = GatewayRead.model_construct(auth_type="authheaders", auth_value=encode_auth(TruthyDict()))
    with pytest.raises(ValueError):
        GatewayRead._populate_auth(empty_headers)


def test_rpc_and_event_admin_and_server_validators(caplog):
    assert RPCRequest(jsonrpc="2.0", method="tools/list", params=None, id=1).params is None

    fixed = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    event = EventMessage(type="tool_added", data={"id": "t1"}, timestamp=fixed)
    dumped = json.loads(event.model_dump_json())
    assert dumped["timestamp"].endswith("Z")

    assert AdminToolCreate.validate_json("") is None

    caplog.set_level("INFO", logger="mcpgateway.schemas")
    long_desc = "x" * (SecurityValidator.MAX_DESCRIPTION_LENGTH + 1)
    assert len(ServerCreate.validate_description(long_desc)) == SecurityValidator.MAX_DESCRIPTION_LENGTH
    assert len(ServerUpdate.validate_description(long_desc)) == SecurityValidator.MAX_DESCRIPTION_LENGTH
    assert any("Description too long" in rec.message for rec in caplog.records)

    with pytest.raises(ValidationError):
        ServerCreate(name="srv", visibility="invalid")

    assert ServerCreate.validate_team_id("550e8400-e29b-41d4-a716-446655440000")

    class AssocObj:
        def __init__(self):
            self.associated_tools = [SimpleNamespace(id="t1"), "t2"]
            self.associated_resources = [SimpleNamespace(id="r1"), "r2"]
            self.associated_prompts = [SimpleNamespace(id="p1")]
            self.associated_a2a_agents = [SimpleNamespace(id="a1"), "a2"]

    data = ServerRead.populate_associated_ids(AssocObj())
    assert data["associated_tools"] == ["t1", "t2"]
    assert data["associated_a2a_agents"] == ["a1", "a2"]

    class NoVars:
        __slots__ = ()

    obj = NoVars()
    assert ServerRead.populate_associated_ids(obj) is obj


def test_a2a_agent_create_and_update_more_branches(monkeypatch, caplog):
    caplog.set_level("WARNING", logger="mcpgateway.schemas")
    long_desc = "x" * (SecurityValidator.MAX_DESCRIPTION_LENGTH + 1)
    assert len(A2AAgentCreate.validate_description(long_desc)) == SecurityValidator.MAX_DESCRIPTION_LENGTH
    assert len(A2AAgentUpdate.validate_description(long_desc)) == SecurityValidator.MAX_DESCRIPTION_LENGTH

    with pytest.raises((ValueError, ValidationError)):
        A2AAgentCreate(name="agent", endpoint_url="http://agent.example.com", visibility="invalid")
    with pytest.raises((ValueError, ValidationError)):
        A2AAgentUpdate(visibility="invalid")

    with pytest.raises((ValidationError, ValueError)):
        A2AAgentCreate(name="agent", endpoint_url="http://agent.example.com", auth_type="basic", auth_username="u")

    # A2AAgentCreate authheaders: skip non-dict, warn on duplicates, and return encoded headers
    encoded = A2AAgentCreate._process_auth_fields(
        SimpleNamespace(
            data={
                "auth_type": "authheaders",
                "auth_headers": ["nope", {"key": "", "value": "x"}, {"key": "X-Token", "value": "a"}, {"key": "X-Token", "value": "b"}],
            }
        )
    )
    assert decode_auth(encoded)["X-Token"] == "b"
    assert any("Duplicate header keys detected" in rec.message for rec in caplog.records)

    with pytest.raises(ValueError):
        A2AAgentCreate._process_auth_fields(SimpleNamespace(data={"auth_type": "authheaders"}))
    assert A2AAgentCreate._process_auth_fields(SimpleNamespace(data={"auth_type": "one_time_auth"})) is None
    with pytest.raises(ValueError):
        A2AAgentCreate._process_auth_fields(SimpleNamespace(data={"auth_type": "invalid"}))

    too_many = [{"key": f"X-{i}", "value": "v"} for i in range(101)]
    with pytest.raises(ValueError):
        A2AAgentCreate._process_auth_fields(SimpleNamespace(data={"auth_type": "authheaders", "auth_headers": too_many}))

    monkeypatch.setattr(settings, "insecure_allow_queryparam_auth", True)
    monkeypatch.setattr(settings, "insecure_queryparam_auth_allowed_hosts", [])
    with pytest.raises((ValidationError, ValueError)):
        A2AAgentCreate(name="agent", endpoint_url="http://agent.example.com", auth_type="query_param", auth_query_param_value="secret")
    with pytest.raises((ValidationError, ValueError)):
        A2AAgentCreate(name="agent", endpoint_url="http://agent.example.com", auth_type="query_param", auth_query_param_key="api_key")

    assert A2AAgentUpdate.validate_tags(None) is None
    assert A2AAgentUpdate.validate_json_fields(None) is None

    # A2AAgentUpdate authheaders: skip non-dict, skip missing key, warn duplicates, and return encoded headers
    encoded = A2AAgentUpdate._process_auth_fields(
        SimpleNamespace(
            data={
                "auth_type": "authheaders",
                "auth_headers": ["nope", {"key": "", "value": "x"}, {"key": "X-Token", "value": "a"}, {"key": "X-Token", "value": "b"}],
            }
        )
    )
    assert decode_auth(encoded)["X-Token"] == "b"

    with pytest.raises((ValidationError, ValueError)):
        A2AAgentUpdate(auth_type="bearer")  # Missing token

    assert A2AAgentUpdate._process_auth_fields(SimpleNamespace(data={"auth_type": "one_time_auth"})) is None
    with pytest.raises(ValueError):
        A2AAgentUpdate._process_auth_fields(SimpleNamespace(data={"auth_type": "invalid"}))

    with pytest.raises((ValidationError, ValueError)):
        A2AAgentUpdate(auth_type="query_param", auth_query_param_value=SecretStr("secret"))


def test_a2a_agent_create_legacy_authheaders_return():
    encoded = A2AAgentCreate._process_auth_fields(SimpleNamespace(data={"auth_type": "authheaders", "auth_header_key": "X-Key", "auth_header_value": "v"}))
    assert decode_auth(encoded)["X-Key"] == "v"


def test_a2a_agent_update_basic_and_authheaders_edge_cases():
    with pytest.raises((ValidationError, ValueError)):
        A2AAgentUpdate(auth_type="basic", auth_username="u")

    updated = A2AAgentUpdate(auth_type="basic", auth_username="u", auth_password="p")
    assert decode_auth(updated.auth_value)["Authorization"].startswith("Basic ")

    with pytest.raises(ValueError):
        A2AAgentUpdate._process_auth_fields(SimpleNamespace(data={"auth_type": "authheaders", "auth_headers": [{"key": "Bad:Key", "value": "v"}]}))

    with pytest.raises(ValueError):
        A2AAgentUpdate._process_auth_fields(SimpleNamespace(data={"auth_type": "authheaders", "auth_headers": [{"key": "", "value": "v"}]}))

    too_many = [{"key": f"X-{i}", "value": "v"} for i in range(101)]
    with pytest.raises(ValueError):
        A2AAgentUpdate._process_auth_fields(SimpleNamespace(data={"auth_type": "authheaders", "auth_headers": too_many}))

    encoded = A2AAgentUpdate._process_auth_fields(SimpleNamespace(data={"auth_type": "authheaders", "auth_header_key": "X-Key", "auth_header_value": "v"}))
    assert decode_auth(encoded)["X-Key"] == "v"

    with pytest.raises(ValueError):
        A2AAgentUpdate._process_auth_fields(SimpleNamespace(data={"auth_type": "authheaders"}))


def test_a2a_agent_read_masking_and_populate_auth_error_paths():
    class DummyAgent:
        __table__ = SimpleNamespace(columns=[SimpleNamespace(name="id"), SimpleNamespace(name="auth_query_params")])

        def __init__(self):
            self.id = "a1"
            self.auth_query_params = {"api_key": "enc"}
            self.team = "Team-1"

    masked_obj = A2AAgentRead._mask_query_param_auth(DummyAgent())
    assert masked_obj["auth_query_param_key"] == "api_key"
    assert masked_obj["team"] == "Team-1"

    masked_value = A2AAgentRead.model_construct(auth_type="basic", auth_value=settings.masked_auth_value)
    assert A2AAgentRead._populate_auth(masked_value) is masked_value

    oauth = A2AAgentRead.model_construct(auth_type="oauth", auth_value=None)
    assert A2AAgentRead._populate_auth(oauth) is oauth

    one_time = A2AAgentRead.model_construct(auth_type="one_time_auth", auth_value=None)
    assert A2AAgentRead._populate_auth(one_time) is one_time

    qp = A2AAgentRead.model_construct(auth_type="query_param", auth_value=None)
    assert A2AAgentRead._populate_auth(qp) is qp

    bad_basic = A2AAgentRead.model_construct(auth_type="basic", auth_value=encode_auth({"Authorization": "Bearer token"}))
    with pytest.raises(ValueError):
        A2AAgentRead._populate_auth(bad_basic)

    encoded_user_only = base64.urlsafe_b64encode("user:".encode("utf-8")).decode("utf-8")
    missing_pw = A2AAgentRead.model_construct(auth_type="basic", auth_value=encode_auth({"Authorization": f"Basic {encoded_user_only}"}))
    with pytest.raises(ValueError):
        A2AAgentRead._populate_auth(missing_pw)

    bad_bearer = A2AAgentRead.model_construct(auth_type="bearer", auth_value=encode_auth({"Authorization": f"Basic {encoded_user_only}"}))
    with pytest.raises(ValueError):
        A2AAgentRead._populate_auth(bad_bearer)

    class TruthyDict(dict):
        def __bool__(self) -> bool:  # pragma: no cover - deterministic helper
            return True

    empty_headers = A2AAgentRead.model_construct(auth_type="authheaders", auth_value=encode_auth(TruthyDict()))
    with pytest.raises(ValueError):
        A2AAgentRead._populate_auth(empty_headers)

    agent = A2AAgentRead(
        name="agent",
        endpoint_url="http://agent.example.com",
        agent_type="generic",
        protocol_version="1.0",
        capabilities={},
        config={},
        enabled=True,
        reachable=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        last_interaction=None,
        auth_type="bearer",
        auth_value=encode_auth({"Authorization": "Bearer token"}),
    )
    masked = agent.masked()
    assert masked.auth_value == settings.masked_auth_value

    invocation = A2AAgentInvocation(agent_name="agent", parameters={"a": 1})
    assert invocation.agent_name == "agent"


def test_password_team_token_and_grpc_validators(monkeypatch):
    with pytest.raises(ValueError):
        ChangePasswordRequest.validate_new_password("short")

    # Slug validator: call directly to bypass Field pattern validation (covers schemas.py validator logic)
    with pytest.raises(ValueError):
        TeamCreateRequest.validate_slug("Invalid_Slug")
    with pytest.raises((ValidationError, ValueError)):
        TeamCreateRequest(name="T", slug="-bad")

    with pytest.raises((ValidationError, ValueError)):
        TeamUpdateRequest(name="   ")
    assert TeamUpdateRequest.validate_name(None) is None
    with pytest.raises(ValueError):
        TeamUpdateRequest.validate_description("javascript:alert(1)")

    # Monkeypatch name pattern to allow colon so we can exercise the dangerous JS pattern check path.
    monkeypatch.setattr(settings, "validation_name_pattern", r"^.+$")
    with pytest.raises(ValueError):
        TeamCreateRequest.validate_name("javascript:alert(1)")
    with pytest.raises(ValueError):
        TeamUpdateRequest.validate_name("javascript:alert(1)")

    assert TokenScopeRequest.validate_ip_restrictions([]) == []
    assert TokenScopeRequest.validate_ip_restrictions(["   ", "10.0.0.1"]) == ["10.0.0.1"]
    assert TokenScopeRequest.validate_permissions([]) == []
    assert TokenScopeRequest.validate_permissions(["   ", "tools.read", "*"]) == ["tools.read", "*"]

    with pytest.raises((ValidationError, ValueError)):
        GrpcServiceCreate(name="svc", target="localhost")
    assert GrpcServiceCreate.validate_description(None) is None
    assert len(GrpcServiceCreate.validate_description("x" * (SecurityValidator.MAX_DESCRIPTION_LENGTH + 1))) == SecurityValidator.MAX_DESCRIPTION_LENGTH

    assert GrpcServiceUpdate.validate_name(None) is None
    assert GrpcServiceUpdate.validate_target(None) is None
    with pytest.raises(ValueError):
        GrpcServiceUpdate.validate_target("host")
    assert GrpcServiceUpdate.validate_description(None) is None
    assert len(GrpcServiceUpdate.validate_description("x" * (SecurityValidator.MAX_DESCRIPTION_LENGTH + 1))) == SecurityValidator.MAX_DESCRIPTION_LENGTH


class TestMaskOauthConfig:
    """Tests for the _mask_oauth_config() helper function."""

    def test_masks_client_secret(self):
        """client_secret is replaced with masked value."""
        result = _mask_oauth_config({"client_secret": "super-secret"})
        assert result["client_secret"] == settings.masked_auth_value

    def test_masks_password(self):
        """password is replaced with masked value."""
        result = _mask_oauth_config({"password": "p@ssw0rd"})
        assert result["password"] == settings.masked_auth_value

    def test_masks_all_sensitive_keys(self):
        """All keys in _SENSITIVE_OAUTH_KEYS are masked."""
        # First-Party
        from mcpgateway.schemas import _SENSITIVE_OAUTH_KEYS

        config = {k: f"value-{k}" for k in _SENSITIVE_OAUTH_KEYS}
        result = _mask_oauth_config(config)
        for k in _SENSITIVE_OAUTH_KEYS:
            assert result[k] == settings.masked_auth_value

    def test_preserves_non_sensitive(self):
        """grant_type, token_url etc. are unchanged."""
        config = {"grant_type": "client_credentials", "token_url": "https://auth.example.com/token", "client_id": "my-app"}
        result = _mask_oauth_config(config)
        assert result == config

    def test_handles_none_values(self):
        """Falsy values (None) are not masked."""
        result = _mask_oauth_config({"password": None})
        assert result["password"] is None

    def test_handles_nested_dicts(self):
        """Recursive masking works on nested dictionaries."""
        config = {"nested": {"client_secret": "inner-secret", "safe_key": "ok"}}
        result = _mask_oauth_config(config)
        assert result["nested"]["client_secret"] == settings.masked_auth_value
        assert result["nested"]["safe_key"] == "ok"

    def test_handles_non_dict(self):
        """String/int/None input is returned as-is."""
        assert _mask_oauth_config("just-a-string") == "just-a-string"
        assert _mask_oauth_config(42) == 42
        assert _mask_oauth_config(None) is None

    def test_case_insensitive(self):
        """Key matching is case-insensitive (lowered comparison)."""
        result = _mask_oauth_config({"Client_Secret": "secret"})
        assert result["Client_Secret"] == settings.masked_auth_value

    def test_handles_list_input(self):
        """Lists are recursively processed."""
        config = [{"client_secret": "s1"}, {"safe_key": "ok"}]
        result = _mask_oauth_config(config)
        assert result[0]["client_secret"] == settings.masked_auth_value
        assert result[1]["safe_key"] == "ok"

    def test_gateway_read_masked_includes_oauth(self):
        """GatewayRead.masked() masks oauth_config sensitive keys."""
        gw = GatewayRead(
            name="test-gw",
            url="http://example.com",
            oauth_config={"client_secret": "secret", "token_url": "https://auth.example.com/token"},
        )
        masked = gw.masked()
        assert masked.oauth_config["client_secret"] == settings.masked_auth_value
        assert masked.oauth_config["token_url"] == "https://auth.example.com/token"

    def test_a2a_agent_read_masked_includes_oauth(self):
        """A2AAgentRead.masked() masks oauth_config sensitive keys."""
        now = datetime.now(timezone.utc)
        agent = A2AAgentRead(
            name="test-agent",
            endpoint_url="http://example.com/agent",
            agent_type="a2a",
            protocol_version="1.0",
            capabilities={},
            config={},
            enabled=True,
            reachable=True,
            created_at=now,
            updated_at=now,
            last_interaction=None,
            oauth_config={"client_secret": "secret", "grant_type": "client_credentials"},
        )
        masked = agent.masked()
        assert masked.oauth_config["client_secret"] == settings.masked_auth_value
        assert masked.oauth_config["grant_type"] == "client_credentials"

    def test_server_read_masked_includes_oauth(self):
        """ServerRead.masked() masks oauth_config sensitive keys."""
        now = datetime.now(timezone.utc)
        server = ServerRead(
            id="srv-1",
            name="srv",
            description=None,
            icon=None,
            created_at=now,
            updated_at=now,
            enabled=True,
            associated_tools=[],
            associated_resources=[],
            associated_prompts=[],
            associated_a2a_agents=[],
            oauth_enabled=True,
            oauth_config={"client_secret": "secret", "authorization_server": "https://idp.example.com"},
        )
        masked = server.masked()
        assert masked.oauth_config["client_secret"] == settings.masked_auth_value
        assert masked.oauth_config["authorization_server"] == "https://idp.example.com"


class TestToolCreateDescriptionValidationStrict:
    """Tests for issue #3711 — VALIDATION_STRICT gates the forbidden-pattern check.

    ToolCreate.validate_description must raise when validation_strict=True (default)
    and must only log a warning when validation_strict=False, so that MCP server
    tools with Markdown-formatted descriptions (e.g. "> blockquote") can register.
    """

    def test_forbidden_pattern_rejected_in_strict_mode(self, monkeypatch):
        """Descriptions with shell/pipe metacharacters raise ValueError when VALIDATION_STRICT=true."""
        monkeypatch.setattr(settings, "validation_strict", True)
        for pat in ["&&", ";", "||", "$(", "|", "> ", "< "]:
            with pytest.raises(ValueError, match="unsafe characters"):
                ToolCreate.validate_description(f"Valid prefix {pat} suffix")

    @pytest.mark.parametrize(
        "description",
        [
            "run cmd1 && cmd2",
            "end statement;",
            "try this || that",
            "expand $(cmd)",
            "pipe | grep",
            "Search docs > results",
            "read < file",
        ],
        ids=["ampersand", "semicolon", "or", "subshell", "pipe", "redirect_out", "redirect_in"],
    )
    def test_forbidden_pattern_allowed_in_non_strict_mode(self, monkeypatch, caplog, description):
        """Each forbidden pattern is accepted (with warning) when VALIDATION_STRICT=false."""
        monkeypatch.setattr(settings, "validation_strict", False)

        with caplog.at_level(logging.WARNING, logger="mcpgateway.schemas"):
            result = ToolCreate.validate_description(description)
        assert result is not None
        assert any("potentially unsafe" in rec.message for rec in caplog.records)

    def test_non_strict_logs_single_warning_for_multiple_patterns(self, monkeypatch, caplog):
        """Only one warning is logged even when a description matches multiple forbidden patterns."""
        monkeypatch.setattr(settings, "validation_strict", False)

        with caplog.at_level(logging.WARNING, logger="mcpgateway.schemas"):
            result = ToolCreate.validate_description("foo && bar | baz > qux")
        assert result is not None
        unsafe_warnings = [r for r in caplog.records if "potentially unsafe" in r.message]
        assert len(unsafe_warnings) == 1

    def test_safe_description_always_accepted(self, monkeypatch):
        """Safe descriptions pass in both strict and non-strict modes."""
        for strict in (True, False):
            monkeypatch.setattr(settings, "validation_strict", strict)
            result = ToolCreate.validate_description("A perfectly safe description.")
            assert result == "A perfectly safe description."

    def test_none_description_always_accepted(self, monkeypatch):
        """None descriptions pass through unchanged in both modes."""
        for strict in (True, False):
            monkeypatch.setattr(settings, "validation_strict", strict)
            assert ToolCreate.validate_description(None) is None


def test_a2a_agent_read_populates_auth_headers_single():
    """Test A2AAgentRead populates auth_headers from single custom header."""
    auth_value = encode_auth({"X-API-Key": "secret123"})
    agent = A2AAgentRead.model_construct(
        id="test-id",
        name="Test Agent",
        endpoint_url="https://api.example.com",
        agent_type="generic",
        protocol_version="1.0",
        capabilities={},
        config={},
        enabled=True,
        reachable=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        auth_type="authheaders",
        auth_value=auth_value,
    )
    agent = agent._populate_auth()

    assert agent.auth_headers is not None
    assert isinstance(agent.auth_headers, list)
    assert len(agent.auth_headers) == 1
    assert agent.auth_headers[0]["key"] == "X-API-Key"
    assert agent.auth_headers[0]["value"] == "secret123"
    # Backward compatibility
    assert agent.auth_header_key == "X-API-Key"
    assert agent.auth_header_value == "secret123"


def test_a2a_agent_read_populates_auth_headers_multiple():
    """Test A2AAgentRead populates auth_headers from multiple custom headers."""
    auth_value = encode_auth({"X-API-Key": "secret123", "X-Client-ID": "client456", "X-Region": "us-east-1"})
    agent = A2AAgentRead.model_construct(
        id="test-id",
        name="Test Agent",
        endpoint_url="https://api.example.com",
        agent_type="generic",
        protocol_version="1.0",
        capabilities={},
        config={},
        enabled=True,
        reachable=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        auth_type="authheaders",
        auth_value=auth_value,
    )
    agent = agent._populate_auth()

    assert agent.auth_headers is not None
    assert len(agent.auth_headers) == 3
    keys = [h["key"] for h in agent.auth_headers]
    assert "X-API-Key" in keys
    assert "X-Client-ID" in keys
    assert "X-Region" in keys


def test_a2a_agent_read_masked_hides_auth_header_values():
    """Test A2AAgentRead.masked() masks auth_headers values."""
    auth_value = encode_auth({"X-API-Key": "secret123", "X-Client-ID": "client456"})
    agent = A2AAgentRead.model_construct(
        id="test-id",
        name="Test Agent",
        endpoint_url="https://api.example.com",
        agent_type="generic",
        protocol_version="1.0",
        capabilities={},
        config={},
        enabled=True,
        reachable=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        last_interaction=None,
        auth_type="authheaders",
        auth_value=auth_value,
    )
    agent = agent._populate_auth()
    masked_agent = agent.masked()

    assert masked_agent.auth_headers is not None
    assert len(masked_agent.auth_headers) == 2
    # Keys should be visible
    assert masked_agent.auth_headers[0]["key"] == "X-API-Key"
    assert masked_agent.auth_headers[1]["key"] == "X-Client-ID"
    # Values should be masked
    assert masked_agent.auth_headers[0]["value"] == settings.masked_auth_value
    assert masked_agent.auth_headers[1]["value"] == settings.masked_auth_value


def test_a2a_agent_read_auth_headers_empty_values():
    """Test A2AAgentRead handles empty header values correctly."""
    auth_value = encode_auth({"X-Empty-Header": ""})
    agent = A2AAgentRead.model_construct(
        id="test-id",
        name="Test Agent",
        endpoint_url="https://api.example.com",
        agent_type="generic",
        protocol_version="1.0",
        capabilities={},
        config={},
        enabled=True,
        reachable=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        auth_type="authheaders",
        auth_value=auth_value,
    )
    agent = agent._populate_auth()

    assert agent.auth_headers[0]["value"] == ""


def test_a2a_agent_read_authheaders_rejects_non_dict():
    """Test A2AAgentRead._populate_auth raises ValueError when decoded auth_value is not a dict."""
    # encode_auth expects a dict, so we encode a list-wrapping hack that decode_auth
    # still returns as a dict.  Instead, manually construct with a raw string to bypass
    # encode_auth and trigger the isinstance guard.
    agent = A2AAgentRead.model_construct(
        id="test-id",
        name="Test Agent",
        endpoint_url="https://api.example.com",
        agent_type="generic",
        protocol_version="1.0",
        capabilities={},
        config={},
        enabled=True,
        reachable=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        auth_type="authheaders",
        auth_value=encode_auth({"_list": ["not-a-dict"]}),
    )
    # Monkey-patch decode_auth to return a non-dict value
    # First-Party
    import mcpgateway.schemas as _schemas_mod

    _original = _schemas_mod.decode_auth

    def _fake_decode(val, **kw):
        return ["not", "a", "dict"]

    _schemas_mod.decode_auth = _fake_decode
    try:
        with pytest.raises(ValueError, match="authheaders requires at least one key/value pair"):
            A2AAgentRead._populate_auth(agent)
    finally:
        _schemas_mod.decode_auth = _original


def test_a2a_agent_read_auth_headers_none_values():
    """Test A2AAgentRead handles None header values by converting to empty string."""
    auth_value = encode_auth({"X-Null-Header": None})
    agent = A2AAgentRead.model_construct(
        id="test-id",
        name="Test Agent",
        endpoint_url="https://api.example.com",
        agent_type="generic",
        protocol_version="1.0",
        capabilities={},
        config={},
        enabled=True,
        reachable=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        auth_type="authheaders",
        auth_value=auth_value,
    )
    agent = agent._populate_auth()

    assert agent.auth_headers[0]["key"] == "X-Null-Header"
    assert agent.auth_headers[0]["value"] == ""


def test_a2a_agent_read_masked_preserves_empty_header_values():
    """Test A2AAgentRead.masked() does not mask empty header values."""
    auth_value = encode_auth({"X-Empty": "", "X-Secret": "real-value"})
    agent = A2AAgentRead.model_construct(
        id="test-id",
        name="Test Agent",
        endpoint_url="https://api.example.com",
        agent_type="generic",
        protocol_version="1.0",
        capabilities={},
        config={},
        enabled=True,
        reachable=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        last_interaction=None,
        auth_type="authheaders",
        auth_value=auth_value,
    )
    agent = agent._populate_auth()
    masked_agent = agent.masked()

    # Empty value should stay empty (not masked)
    empty_header = next(h for h in masked_agent.auth_headers if h["key"] == "X-Empty")
    assert empty_header["value"] == ""
    # Non-empty value should be masked
    secret_header = next(h for h in masked_agent.auth_headers if h["key"] == "X-Secret")
    assert secret_header["value"] == settings.masked_auth_value


def test_visibility_literal_enum_validation():
    """Schemas with Literal visibility reject invalid values and accept valid ones (issue #3525)."""
    valid_values = ["private", "team", "public"]
    invalid_values = ["invalid_value", "", "PUBLIC", "PRIVATE", "admin", "internal"]

    # GatewayUpdate — the primary schema from the issue
    for v in valid_values:
        obj = GatewayUpdate(visibility=v)
        assert obj.visibility == v
    for v in invalid_values:
        with pytest.raises(ValidationError):
            GatewayUpdate(visibility=v)
    assert GatewayUpdate().visibility is None  # default is None (optional)

    # GatewayCreate
    for v in valid_values:
        assert GatewayCreate(name="gw", url="http://localhost:9000", visibility=v).visibility == v
    for v in invalid_values:
        with pytest.raises(ValidationError):
            GatewayCreate(name="gw", url="http://localhost:9000", visibility=v)

    # ToolUpdate
    for v in valid_values:
        obj = ToolUpdate(visibility=v)
        assert obj.visibility == v
    for v in invalid_values:
        with pytest.raises(ValidationError):
            ToolUpdate(visibility=v)

    # ToolCreate — default is None (inherits from gateway during MCP discovery)
    for v in valid_values:
        obj = ToolCreate(name="t", url="http://localhost:9000/tool", integration_type="REST", request_type="POST", visibility=v)
        assert obj.visibility == v
    for v in invalid_values:
        with pytest.raises(ValidationError):
            ToolCreate(name="t", url="http://localhost:9000/tool", integration_type="REST", request_type="POST", visibility=v)
    assert ToolCreate(name="t", url="http://localhost:9000/tool", integration_type="REST", request_type="POST").visibility is None

    # ResourceUpdate
    for v in valid_values:
        obj = ResourceUpdate(visibility=v)
        assert obj.visibility == v
    for v in invalid_values:
        with pytest.raises(ValidationError):
            ResourceUpdate(visibility=v)

    # PromptUpdate
    for v in valid_values:
        obj = PromptUpdate(visibility=v)
        assert obj.visibility == v
    for v in invalid_values:
        with pytest.raises(ValidationError):
            PromptUpdate(visibility=v)

    # GrpcServiceUpdate
    for v in valid_values:
        obj = GrpcServiceUpdate(visibility=v)
        assert obj.visibility == v
    for v in invalid_values:
        with pytest.raises(ValidationError):
            GrpcServiceUpdate(visibility=v)

    # GrpcServiceCreate — required fields: name, target
    for v in valid_values:
        obj = GrpcServiceCreate(name="svc", target="localhost:50051", visibility=v)
        assert obj.visibility == v
    for v in invalid_values:
        with pytest.raises(ValidationError):
            GrpcServiceCreate(name="svc", target="localhost:50051", visibility=v)

    # ResourceCreate — default is None (inherits from gateway during MCP discovery)
    for v in valid_values:
        obj = ResourceCreate(uri="file:///tmp/r.txt", name="r", content="data", visibility=v)
        assert obj.visibility == v
    for v in invalid_values:
        with pytest.raises(ValidationError):
            ResourceCreate(uri="file:///tmp/r.txt", name="r", content="data", visibility=v)
    assert ResourceCreate(uri="file:///tmp/r.txt", name="r", content="data").visibility is None

    # PromptCreate — default is None (inherits from gateway during MCP discovery)
    for v in valid_values:
        obj = PromptCreate(name="p", template="hello", visibility=v)
        assert obj.visibility == v
    for v in invalid_values:
        with pytest.raises(ValidationError):
            PromptCreate(name="p", template="hello", visibility=v)
    assert PromptCreate(name="p", template="hello").visibility is None

    # ServerCreate — required field: name
    for v in valid_values:
        obj = ServerCreate(name="srv", visibility=v)
        assert obj.visibility == v
    for v in invalid_values:
        with pytest.raises(ValidationError):
            ServerCreate(name="srv", visibility=v)
    assert ServerCreate(name="srv", visibility=None).visibility is None

    # ServerUpdate — all fields optional
    for v in valid_values:
        obj = ServerUpdate(visibility=v)
        assert obj.visibility == v
    for v in invalid_values:
        with pytest.raises(ValidationError):
            ServerUpdate(visibility=v)
    assert ServerUpdate().visibility is None

    # A2AAgentCreate — required fields: name, endpoint_url
    for v in valid_values:
        obj = A2AAgentCreate(name="agent", endpoint_url="http://localhost:8080", visibility=v)
        assert obj.visibility == v
    for v in invalid_values:
        with pytest.raises(ValidationError):
            A2AAgentCreate(name="agent", endpoint_url="http://localhost:8080", visibility=v)
    assert A2AAgentCreate(name="agent", endpoint_url="http://localhost:8080", visibility=None).visibility is None

    # A2AAgentUpdate — all fields optional
    for v in valid_values:
        obj = A2AAgentUpdate(visibility=v)
        assert obj.visibility == v
    for v in invalid_values:
        with pytest.raises(ValidationError):
            A2AAgentUpdate(visibility=v)
    assert A2AAgentUpdate().visibility is None


def test_coerce_visibility_normalizes_invalid_values():
    """_coerce_visibility must normalize invalid legacy values to 'public' instead of raising."""
    assert _coerce_visibility("bogus") == "public"
    assert _coerce_visibility("") == "public"
    assert _coerce_visibility("PUBLIC") == "public"
    assert _coerce_visibility("PRIVATE") == "public"
    # Valid values pass through unchanged
    assert _coerce_visibility("private") == "private"
    assert _coerce_visibility("team") == "team"
    assert _coerce_visibility("public") == "public"
    assert _coerce_visibility(None) is None


def test_read_schemas_have_visibility_coercion_wired():
    """All Read schemas must have _normalize_visibility wired so legacy DB rows don't crash reads."""
    for schema_cls in [ToolRead, ResourceRead, PromptRead, GatewayRead, ServerRead, A2AAgentRead, GrpcServiceRead]:
        assert hasattr(schema_cls, "_normalize_visibility"), f"{schema_cls.__name__} missing _normalize_visibility"
