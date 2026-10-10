# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_error_formatter.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Full-coverage unit tests for **mcpgateway.utils.error_formatter**
Running:
    pytest -q --cov=mcpgateway.utils.error_formatter --cov-report=term-missing
Should show **100 %** statement coverage for the target module.
Author: Mihai Criveti
"""

# Standard
from unittest.mock import Mock

# Third-Party
from pydantic import BaseModel, field_validator, ValidationError
import pytest
from sqlalchemy.exc import DatabaseError, IntegrityError

# First-Party
from mcpgateway.common.validators import UrlPolicyError
from mcpgateway.utils.error_formatter import ErrorFormatter, sanitize_validation_error_for_log


class NameModel(BaseModel):
    name: str

    @field_validator("name")
    def validate_name(cls, v):
        if not v.startswith("A"):
            raise ValueError("Tool name must start with a letter, number, or underscore")
        if len(v) > 255:
            raise ValueError("Tool name exceeds maximum length")
        return v


class UrlModel(BaseModel):
    url: str

    @field_validator("url")
    def validate_url(cls, v):
        if not v.startswith("http"):
            raise ValueError("Tool URL must start with http")
        return v


class PathModel(BaseModel):
    path: str

    @field_validator("path")
    def validate_path(cls, v):
        if ".." in v:
            raise ValueError("cannot contain directory traversal")
        return v


class ContentModel(BaseModel):
    content: str

    @field_validator("content")
    def validate_content(cls, v):
        if "<" in v and ">" in v:
            raise ValueError("contains HTML tags")
        return v


def test_format_validation_error_never_leaks_pydantic_internals():
    """The response carries field-level messages but no class name, version URL, or submitted value."""

    class GatewayCreate(BaseModel):
        count: int
        name: str

    with pytest.raises(ValidationError) as exc:
        GatewayCreate(count="lots", name=12345)
    result = ErrorFormatter.format_validation_error(exc.value)
    rendered = str(result)
    assert result["success"] is False
    assert result["detail"] == result["message"]
    assert {d["field"] for d in result["details"]} == {"count", "name"}
    assert "GatewayCreate" not in rendered
    assert "pydantic" not in rendered.lower()
    assert "input_value" not in rendered
    assert "lots" not in rendered and "12345" not in rendered


def test_format_validation_error_neutralises_class_name_error_types():
    """Nested-model type errors embed the class name in Pydantic's msg; those are replaced."""

    class Inner(BaseModel):
        x: int

    class Outer(BaseModel):
        inner: Inner

    with pytest.raises(ValidationError) as exc:
        Outer(inner="not-a-dict")
    result = ErrorFormatter.format_validation_error(exc.value)
    assert result["details"][0] == {"field": "inner", "message": "Invalid inner"}
    assert "Inner" not in str(result)


def test_format_validation_error_empty_errors():
    """With an empty errors list, the summary defaults to 'Validation error' (no NameError)."""
    # Craft a ValidationError mock whose .errors() returns []
    mock_exc = Mock(spec=ValidationError)
    mock_exc.errors = lambda: []
    result = ErrorFormatter.format_validation_error(mock_exc)
    assert result["success"] is False
    assert result["details"] == []
    assert result["message"] == "Validation failed: Validation error"


def test_format_validation_error_letter_requirement():
    with pytest.raises(ValidationError) as exc:
        NameModel(name="Bobby")
    result = ErrorFormatter.format_validation_error(exc.value)
    assert result["message"] == "Validation failed: Name must start with a letter, number, or underscore and contain only letters, numbers, periods, underscores, hyphens, and slashes"
    assert result["success"] is False
    assert result["details"][0]["field"] == "name"
    assert "must start with a letter, number, or underscore" in result["details"][0]["message"]


def test_format_validation_error_length():
    with pytest.raises(ValidationError) as exc:
        NameModel(name="A" * 300)
    result = ErrorFormatter.format_validation_error(exc.value)
    assert "too long" in result["details"][0]["message"]


def test_format_validation_error_url():
    with pytest.raises(ValidationError) as exc:
        UrlModel(url="ftp://example.com")
    result = ErrorFormatter.format_validation_error(exc.value)
    assert "valid HTTP" in result["details"][0]["message"]


def test_format_validation_error_directory_traversal():
    with pytest.raises(ValidationError) as exc:
        PathModel(path="../etc/passwd")
    result = ErrorFormatter.format_validation_error(exc.value)
    assert "invalid characters" in result["details"][0]["message"]


def test_format_validation_error_html_injection():
    with pytest.raises(ValidationError) as exc:
        ContentModel(content="<script>alert(1)</script>")
    result = ErrorFormatter.format_validation_error(exc.value)
    assert "cannot contain HTML" in result["details"][0]["message"]


def test_format_validation_error_custom_message_passes_through():
    """A project validator's own message is user-facing; it is returned minus Pydantic's 'Value error, ' prefix."""

    class CustomModel(BaseModel):
        custom: str

        @field_validator("custom")
        def validate_custom(cls, v):
            raise ValueError("Some unknown error")

    with pytest.raises(ValidationError) as exc:
        CustomModel(custom="foo")
    result = ErrorFormatter.format_validation_error(exc.value)
    assert result["details"][0]["message"] == "Some unknown error"


def test_format_validation_error_multiple_fields():
    class MultiModel(BaseModel):
        name: str
        url: str

        @field_validator("name")
        def validate_name(cls, v):
            if len(v) > 255:
                raise ValueError("Tool name exceeds maximum length")
            return v

        @field_validator("url")
        def validate_url(cls, v):
            if not v.startswith("http"):
                raise ValueError("Tool URL must start with http")
            return v

    with pytest.raises(ValidationError) as exc:
        MultiModel(name="A" * 300, url="ftp://bad")
    result = ErrorFormatter.format_validation_error(exc.value)
    assert len(result["details"]) == 2
    messages = [d["message"] for d in result["details"]]
    assert any("too long" in m for m in messages)
    assert any("valid HTTP" in m for m in messages)
    # The one-line summary lists every field's message, not just the last one
    assert result["message"] == "Validation failed: " + "; ".join(messages)


def test_get_user_message_all_patterns():
    # Directly test _get_user_message for all mappings and fallback
    assert "must start with a letter, number, or underscore" in ErrorFormatter._get_user_message("name", "Tool name must start with a letter, number, or underscore")
    assert "too long" in ErrorFormatter._get_user_message("description", "Tool name exceeds maximum length")
    assert "valid HTTP" in ErrorFormatter._get_user_message("endpoint", "Tool URL must start with http")
    assert "invalid characters" in ErrorFormatter._get_user_message("path", "cannot contain directory traversal")
    assert "cannot contain HTML" in ErrorFormatter._get_user_message("content", "contains HTML tags")
    assert ErrorFormatter._get_user_message("foo", "random error") == "random error"
    assert ErrorFormatter._get_user_message("foo", "Value error, random error", "value_error") == "random error"
    assert ErrorFormatter._get_user_message("foo", "Assertion failed, nope", "assertion_error") == "nope"
    assert ErrorFormatter._get_user_message("foo", "Input should be an instance of Secret", "is_instance_of") == "Invalid foo"
    assert ErrorFormatter._get_user_message("foo", "", "string_type") == "Invalid foo"


def test_format_request_validation_error_keeps_fastapi_shape_without_leaky_fields():
    """Request-parsing errors keep type/loc/msg (and primitive ctx) but drop input, url, and exception ctx."""
    fake = Mock()
    fake.errors = lambda: [
        {
            "type": "string_too_short",
            "loc": ("body", "name"),
            "msg": "String should have at least 3 characters",
            "input": "ab",
            "url": "https://errors.pydantic.dev/2.13/v/string_too_short",
            "ctx": {"min_length": 3, "error": ValueError("internal")},
        },
        {"type": "model_type", "loc": ("body", "auth"), "msg": "Input should be a valid dictionary or instance of AuthConfig", "input": {}},
        {"type": "missing", "loc": (), "msg": "Field required"},
    ]
    out = ErrorFormatter.format_request_validation_error(fake)
    assert out == [
        {"type": "string_too_short", "loc": ["body", "name"], "msg": "String should have at least 3 characters", "ctx": {"min_length": 3}},
        {"type": "model_type", "loc": ["body", "auth"], "msg": "Invalid auth"},
        {"type": "missing", "loc": [], "msg": "Field required"},
    ]
    assert "AuthConfig" not in str(out) and "pydantic" not in str(out) and "internal" not in str(out)


def test_format_request_validation_error_real_pydantic_error():
    class M(BaseModel):
        count: int

    with pytest.raises(ValidationError) as exc:
        M(count="lots")
    out = ErrorFormatter.format_request_validation_error(exc.value)
    assert out[0]["loc"] == ["count"]
    assert out[0]["type"] == "int_parsing"
    assert "input" not in out[0] and "url" not in out[0]


TOKEN_NAME_CONFLICT = "A token with this name already exists for this user in the same team scope. Token names must be unique per user per team. Please choose a different name."


def make_mock_integrity_error(msg):
    mock = Mock(spec=IntegrityError)
    mock.orig = Mock()
    mock.orig.__str__ = lambda self=mock.orig: msg
    return mock


@pytest.mark.parametrize(
    "msg,expected",
    [
        ("UNIQUE constraint failed: gateways.url", "A gateway with this URL already exists"),
        ("UNIQUE constraint failed: gateways.slug", "A gateway with this name already exists"),
        ("UNIQUE constraint failed: tools.name", "A tool with this name already exists"),
        # Resource URI uniqueness - SQLite single-column variant
        (
            "UNIQUE constraint failed: resources.uri",
            "A resource with this URI already exists in this scope. Resource URIs must be unique; names may repeat.",
        ),
        # Resource URI uniqueness - SQLite multi-column variant emitted by the real composite constraint
        (
            "UNIQUE constraint failed: resources.team_id, resources.owner_email, resources.gateway_id, resources.uri",
            "A resource with this URI already exists in this scope. Resource URIs must be unique; names may repeat.",
        ),
        # Resource URI uniqueness - PostgreSQL reports the constraint name, not column paths
        (
            "uq_team_owner_gateway_uri_resource",
            "A resource with this URI already exists in this scope. Resource URIs must be unique; names may repeat.",
        ),
        (
            "uq_team_owner_uri_resource_local",
            "A resource with this URI already exists in this scope. Resource URIs must be unique; names may repeat.",
        ),
        # Resource URI uniqueness - realistic full PostgreSQL error text
        (
            'duplicate key value violates unique constraint "uq_team_owner_gateway_uri_resource"',
            "A resource with this URI already exists in this scope. Resource URIs must be unique; names may repeat.",
        ),
        (
            'duplicate key value violates unique constraint "uq_team_owner_uri_resource_local"',
            "A resource with this URI already exists in this scope. Resource URIs must be unique; names may repeat.",
        ),
        ("UNIQUE constraint failed: servers.name", "A server with this name already exists"),
        ("UNIQUE constraint failed: prompts.name", "A prompt with this name already exists"),
        ("UNIQUE constraint failed: servers.id", "A server with this ID already exists"),
        ("UNIQUE constraint failed: a2a_agents.slug", "An A2A agent with this name already exists"),
        ("FOREIGN KEY constraint failed", "Referenced item not found"),
        ("NOT NULL constraint failed", "Required field is missing"),
        ("CHECK constraint failed: invalid_data", "Validation failed. Please check the input data."),
        # Token name uniqueness – every constraint spelling maps to the same specific message
        ("uq_email_api_tokens_user_name_team", TOKEN_NAME_CONFLICT),
        ("uq_email_api_tokens_user_name", TOKEN_NAME_CONFLICT),
        ("uq_email_api_tokens_user_email_name", TOKEN_NAME_CONFLICT),
        ("UNIQUE constraint failed: email_api_tokens.user_email, email_api_tokens.name", TOKEN_NAME_CONFLICT),
        ("uq_email_api_tokens_user_name_global", TOKEN_NAME_CONFLICT),
    ],
)
def test_format_database_error_integrity_patterns(msg, expected):
    err = make_mock_integrity_error(msg)
    result = ErrorFormatter.format_database_error(err)
    assert result["message"] == expected
    assert result["success"] is False


def test_format_database_error_generic_integrity():
    err = make_mock_integrity_error("SOME OTHER ERROR")
    result = ErrorFormatter.format_database_error(err)
    assert result["message"].startswith("Unable to complete")
    assert result["success"] is False


def test_format_database_error_unique_constraint_unknown_table_falls_back():
    """Unique constraint errors without a known mapping should use the generic message."""
    err = make_mock_integrity_error("UNIQUE constraint failed: unknown.table")
    result = ErrorFormatter.format_database_error(err)
    assert result["message"].startswith("Unable to complete")
    assert result["success"] is False


def test_format_database_error_generic_database():
    mock = Mock(spec=DatabaseError)
    mock.orig = None
    result = ErrorFormatter.format_database_error(mock)
    assert result["message"].startswith("Unable to complete")
    assert result["success"] is False


def test_format_database_error_no_orig():
    # Simulate error without .orig attribute
    class DummyError(Exception):
        pass

    dummy = DummyError("fail")
    result = ErrorFormatter.format_database_error(dummy)
    assert result["message"].startswith("Unable to complete")
    assert result["success"] is False


def test_safe_error_detail_never_returns_exception_text():
    """safe_error_detail always returns the fallback; raw exception text never reaches a response."""
    from mcpgateway.utils.error_formatter import safe_error_detail

    result = safe_error_detail(ValueError("UNIQUE constraint failed: tools.name"), "Generic fallback")
    assert result == "Generic fallback"
    assert safe_error_detail(RuntimeError("boom")) == "Invalid request. Please check your input and try again."


def test_public_validation_error_is_value_error():
    """Test that PublicValidationError is a subclass of ValueError."""
    from mcpgateway.utils.error_formatter import PublicValidationError

    err = PublicValidationError("Token expiration cannot exceed 365 days")
    assert isinstance(err, ValueError)
    assert str(err) == "Token expiration cannot exceed 365 days"


def test_format_database_error_token_uniqueness_specific_message():
    """Token uniqueness errors always return the specific, user-actionable message (no schema names)."""
    from sqlalchemy.exc import IntegrityError

    orig = Exception("uq_email_api_tokens_user_name_team")
    err = IntegrityError("INSERT", {}, orig)
    result = ErrorFormatter.format_database_error(err)
    assert "unique per user per team" in result["message"]
    assert "uq_email_api_tokens" not in result["message"]
    assert result["success"] is False


def test_sanitize_validation_error_for_log_omits_input_values():
    """sanitize_validation_error_for_log must not include msg, input, or input_value in output."""
    with pytest.raises(ValidationError) as exc:
        NameModel(name="sensitive-value-should-not-appear")
    result = sanitize_validation_error_for_log(exc.value)
    assert "sensitive-value-should-not-appear" not in result
    assert "error(s)" in result
    assert "loc=" in result
    assert "type=" in result


def test_sanitize_validation_error_for_log_format():
    """sanitize_validation_error_for_log returns count and loc/type for each error."""
    with pytest.raises(ValidationError) as exc:
        NameModel(name="Bobby")
    result = sanitize_validation_error_for_log(exc.value)
    assert result.startswith("1 error(s):")
    assert "loc=" in result
    assert "type=" in result


def test_sanitize_validation_error_for_log_bad_errors_method():
    """sanitize_validation_error_for_log returns safe fallback when .errors() raises."""
    bad = Mock()
    bad.errors = Mock(side_effect=RuntimeError("boom"))
    result = sanitize_validation_error_for_log(bad)
    assert "could not extract detail" in result


class ReasonCodeModel(BaseModel):
    """Model whose validator raises reason-coded URL policy errors."""

    url: str

    @field_validator("url")
    @classmethod
    def reject(cls, v):
        """Raise a policy error whose reason code is the submitted value."""
        raise UrlPolicyError(v, "rejected by policy")


def _url_error(reason_code: str) -> ValidationError:
    """Build a ValidationError carrying the given reason code."""
    with pytest.raises(ValidationError) as exc:
        ReasonCodeModel(url=reason_code)
    return exc.value


def test_sanitize_validation_error_for_log_includes_reason_code():
    """Distinct URL failures are distinguishable in logs by reason code."""
    blocked = sanitize_validation_error_for_log(_url_error("url_destination_blocked"))
    dns = sanitize_validation_error_for_log(_url_error("url_dns_resolution_failed"))
    assert "reason_code=url_destination_blocked" in blocked
    assert "reason_code=url_dns_resolution_failed" in dns
    assert blocked != dns


def test_sanitize_validation_error_for_log_rejects_non_code_attribute():
    """Only lowercase snake-case codes are logged, so arbitrary text cannot be injected."""
    result = sanitize_validation_error_for_log(_url_error("Not A Code\nINJECTED"))
    assert "reason_code=" not in result
    assert "INJECTED" not in result


def test_format_validation_error_withholds_destination_reason_codes():
    """Destination and DNS codes stay out of responses: echoing them is an SSRF oracle."""
    blocked = ErrorFormatter.format_validation_error(_url_error("url_private_network_blocked"))
    syntax = ErrorFormatter.format_validation_error(_url_error("url_invalid_syntax"))
    assert "reason_code" not in blocked
    assert syntax["reason_code"] == "url_invalid_syntax"
