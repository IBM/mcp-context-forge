# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_error_formatter.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

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
from mcpgateway.utils.error_formatter import ErrorFormatter


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


def test_format_validation_error_fallback():
    class CustomModel(BaseModel):
        custom: str

        @field_validator("custom")
        def validate_custom(cls, v):
            raise ValueError("Some unknown error")

    with pytest.raises(ValidationError) as exc:
        CustomModel(custom="foo")
    result = ErrorFormatter.format_validation_error(exc.value)
    assert result["details"][0]["message"] == "Invalid custom"


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


def test_get_user_message_all_patterns():
    # Directly test _get_user_message for all mappings and fallback
    assert "must start with a letter, number, or underscore" in ErrorFormatter._get_user_message("name", "Tool name must start with a letter, number, or underscore")
    assert "too long" in ErrorFormatter._get_user_message("description", "Tool name exceeds maximum length")
    assert "valid HTTP" in ErrorFormatter._get_user_message("endpoint", "Tool URL must start with http")
    assert "invalid characters" in ErrorFormatter._get_user_message("path", "cannot contain directory traversal")
    assert "cannot contain HTML" in ErrorFormatter._get_user_message("content", "contains HTML tags")
    assert ErrorFormatter._get_user_message("foo", "random error") == "Invalid foo"


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
        ("UNIQUE constraint failed: resources.uri", "A resource with this URI already exists"),
        ("UNIQUE constraint failed: servers.name", "A server with this name already exists"),
        ("UNIQUE constraint failed: prompts.name", "A prompt with this name already exists"),
        ("UNIQUE constraint failed: servers.id", "A server with this ID already exists"),
        ("UNIQUE constraint failed: a2a_agents.slug", "An A2A agent with this name already exists"),
        ("FOREIGN KEY constraint failed", "Referenced item not found"),
        ("NOT NULL constraint failed", "Required field is missing"),
        ("CHECK constraint failed: invalid_data", "Validation failed. Please check the input data."),
        # Token name uniqueness – new per-team constraint name (sanitized in production)
        (
            "uq_email_api_tokens_user_name_team",
            "A token with this name already exists. Please choose a different name.",
        ),
        # Token name uniqueness – legacy ORM constraint name (sanitized in production)
        ("uq_email_api_tokens_user_name", "A token with this name already exists. Please choose a different name."),
        # Token name uniqueness – Alembic migration constraint name (sanitized in production)
        (
            "uq_email_api_tokens_user_email_name",
            "A token with this name already exists. Please choose a different name.",
        ),
        # Token name uniqueness – SQLite column-path variant (sanitized in production)
        (
            "UNIQUE constraint failed: email_api_tokens.user_email, email_api_tokens.name",
            "A token with this name already exists. Please choose a different name.",
        ),
        # Token name uniqueness – partial unique index for global-scope tokens (sanitized in production)
        (
            "uq_email_api_tokens_user_name_global",
            "A token with this name already exists. Please choose a different name.",
        ),
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


def test_should_expose_error_details_expose_flag_true(monkeypatch):
    """Test that EXPOSE_ERROR_DETAILS=true enables verbose errors."""
    from mcpgateway.utils.error_formatter import should_expose_error_details
    from unittest.mock import MagicMock

    mock_settings = MagicMock()
    mock_settings.expose_error_details = True
    mock_settings.debug = False
    mock_settings.dev_mode = False
    monkeypatch.setattr("mcpgateway.utils.error_formatter.get_settings", lambda: mock_settings)

    assert should_expose_error_details() is True


def test_should_expose_error_details_debug_and_dev_mode(monkeypatch):
    """Test that DEBUG=true AND DEV_MODE=true enables verbose errors."""
    from mcpgateway.utils.error_formatter import should_expose_error_details
    from unittest.mock import MagicMock

    mock_settings = MagicMock()
    mock_settings.expose_error_details = False
    mock_settings.debug = True
    mock_settings.dev_mode = True
    monkeypatch.setattr("mcpgateway.utils.error_formatter.get_settings", lambda: mock_settings)

    assert should_expose_error_details() is True


def test_should_expose_error_details_debug_only_false(monkeypatch):
    """Test that DEBUG=true alone does NOT enable verbose errors."""
    from mcpgateway.utils.error_formatter import should_expose_error_details
    from unittest.mock import MagicMock

    mock_settings = MagicMock()
    mock_settings.expose_error_details = False
    mock_settings.debug = True
    mock_settings.dev_mode = False
    monkeypatch.setattr("mcpgateway.utils.error_formatter.get_settings", lambda: mock_settings)

    assert should_expose_error_details() is False


def test_should_expose_error_details_all_false(monkeypatch):
    """Test that all flags false returns False."""
    from mcpgateway.utils.error_formatter import should_expose_error_details
    from unittest.mock import MagicMock

    mock_settings = MagicMock()
    mock_settings.expose_error_details = False
    mock_settings.debug = False
    mock_settings.dev_mode = False
    monkeypatch.setattr("mcpgateway.utils.error_formatter.get_settings", lambda: mock_settings)

    assert should_expose_error_details() is False


def test_safe_error_detail_verbose_mode(monkeypatch):
    """Test safe_error_detail returns exception text in verbose mode."""
    from mcpgateway.utils.error_formatter import safe_error_detail

    monkeypatch.setattr("mcpgateway.utils.error_formatter.should_expose_error_details", lambda: True)

    result = safe_error_detail(ValueError("Detailed error message"), "Generic fallback")
    assert result == "Detailed error message"


def test_safe_error_detail_production_mode(monkeypatch):
    """Test safe_error_detail returns fallback in production mode."""
    from mcpgateway.utils.error_formatter import safe_error_detail

    monkeypatch.setattr("mcpgateway.utils.error_formatter.should_expose_error_details", lambda: False)

    result = safe_error_detail(ValueError("Detailed error message"), "Generic fallback")
    assert result == "Generic fallback"


def test_public_validation_error_is_value_error():
    """Test that PublicValidationError is a subclass of ValueError."""
    from mcpgateway.utils.error_formatter import PublicValidationError

    err = PublicValidationError("Token expiration cannot exceed 365 days")
    assert isinstance(err, ValueError)
    assert str(err) == "Token expiration cannot exceed 365 days"


def test_format_database_error_token_uniqueness_verbose(monkeypatch):
    """Test that token uniqueness errors expose detail in verbose mode."""
    from sqlalchemy.exc import IntegrityError

    monkeypatch.setattr("mcpgateway.utils.error_formatter.should_expose_error_details", lambda: True)

    orig = Exception("uq_email_api_tokens_user_name_team")
    err = IntegrityError("INSERT", {}, orig)
    result = ErrorFormatter.format_database_error(err)
    assert "unique per user per team" in result["message"]
    assert result["success"] is False


def test_format_database_error_token_uniqueness_production(monkeypatch):
    """Test that token uniqueness errors are sanitized in production mode."""
    from sqlalchemy.exc import IntegrityError

    monkeypatch.setattr("mcpgateway.utils.error_formatter.should_expose_error_details", lambda: False)

    orig = Exception("uq_email_api_tokens_user_name_team")
    err = IntegrityError("INSERT", {}, orig)
    result = ErrorFormatter.format_database_error(err)
    assert "already exists" in result["message"]
    assert "unique per user per team" not in result["message"]
    assert result["success"] is False
