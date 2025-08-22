# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_error_formatter.py
Copyright 2025
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
            raise ValueError("Tool name must start with a letter")
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
    assert result["message"] == "Validation failed: Name must start with a letter and contain only letters, numbers, and underscores"
    assert result["success"] is False
    assert result["details"][0]["field"] == "name"
    assert "must start with a letter" in result["details"][0]["message"]


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
    assert "must start with a letter" in ErrorFormatter._get_user_message("name", "Tool name must start with a letter")
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
        ("UNIQUE constraint failed: gateways.name", "A gateway with this name already exists"),
        ("UNIQUE constraint failed: tools.name", "A tool with this name already exists"),
        ("UNIQUE constraint failed: resources.uri", "A resource with this URI already exists"),
        ("UNIQUE constraint failed: servers.name", "A server with this name already exists"),
        ("FOREIGN KEY constraint failed", "Referenced item not found"),
        ("NOT NULL constraint failed", "Required field is missing"),
        ("CHECK constraint failed: invalid_data", "Validation failed. Please check the input data."),
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
