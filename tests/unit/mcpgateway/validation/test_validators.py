# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/validation/test_validators.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test the validators module.
Author: Madhav Kandukuri
"""

# Standard
from unittest.mock import patch

# Third-Party
import pytest

# First-Party
from mcpgateway.common.validators import SecurityValidator


class DummySettings:
    # Updated to match the patterns in the code (no double escaping)
    validation_dangerous_html_pattern = r"<(script|iframe|object|embed|link|meta|base|form)\b|</*(script|iframe|object|embed|link|meta|base|form)>"
    validation_dangerous_js_pattern = r"javascript:|vbscript:|on\w+\s*=|data:.*script"  # <-- fix: single backslash
    validation_allowed_url_schemes = ["http://", "https://", "ws://", "wss://"]
    validation_name_pattern = r"^[a-zA-Z0-9_\-]+$"
    validation_identifier_pattern = r"^[a-zA-Z0-9_\-\.]+$"
    validation_safe_uri_pattern = r"^[a-zA-Z0-9_\-.:/?=&%{}]+$"
    validation_unsafe_uri_pattern = r"[<>\"'\\]"
    validation_tool_name_pattern = r"^[a-zA-Z][a-zA-Z0-9_]*$"
    validation_max_name_length = 10  # Increased for realistic URIs
    validation_max_description_length = 100
    validation_max_template_length = 100
    validation_max_content_length = 1000
    validation_max_json_depth = 3
    validation_max_url_length = 50  # Increased for realistic URLs
    validation_allowed_mime_types = ["application/json", "text/plain"]


@pytest.fixture(autouse=True)
def patch_logger(monkeypatch):
    logs = []

    class DummyLogger:
        def __getattr__(self, name):
            def logfn(*args, **kwargs):
                logs.append((name, args, kwargs))

            return logfn

    monkeypatch.setattr("mcpgateway.common.validators.logger", DummyLogger())
    yield logs


@pytest.fixture(autouse=True)
def patch_settings_and_classvars(monkeypatch):
    with patch("mcpgateway.config.settings", new=DummySettings):
        SecurityValidator.MAX_NAME_LENGTH = DummySettings.validation_max_name_length
        SecurityValidator.MAX_DESCRIPTION_LENGTH = DummySettings.validation_max_description_length
        SecurityValidator.MAX_TEMPLATE_LENGTH = DummySettings.validation_max_template_length
        SecurityValidator.MAX_CONTENT_LENGTH = DummySettings.validation_max_content_length
        SecurityValidator.MAX_JSON_DEPTH = DummySettings.validation_max_json_depth
        SecurityValidator.MAX_URL_LENGTH = DummySettings.validation_max_url_length
        SecurityValidator.DANGEROUS_HTML_PATTERN = DummySettings.validation_dangerous_html_pattern
        SecurityValidator.DANGEROUS_JS_PATTERN = DummySettings.validation_dangerous_js_pattern
        SecurityValidator.ALLOWED_URL_SCHEMES = DummySettings.validation_allowed_url_schemes
        SecurityValidator.NAME_PATTERN = DummySettings.validation_name_pattern
        SecurityValidator.IDENTIFIER_PATTERN = DummySettings.validation_identifier_pattern
        SecurityValidator.VALIDATION_SAFE_URI_PATTERN = DummySettings.validation_safe_uri_pattern
        SecurityValidator.VALIDATION_UNSAFE_URI_PATTERN = DummySettings.validation_unsafe_uri_pattern
        SecurityValidator.TOOL_NAME_PATTERN = DummySettings.validation_tool_name_pattern
        yield


def test_sanitize_display_text_valid(patch_logger):
    assert SecurityValidator.sanitize_display_text("Hello World", "desc") == "Hello World"
    assert not patch_logger  # No log for valid


def test_sanitize_display_text_html(patch_logger):
    # Should match <script> tag
    with pytest.raises(ValueError):
        SecurityValidator.sanitize_display_text("<script>alert(1)</script>", "desc")
    # Should match <iframe> tag
    with pytest.raises(ValueError):
        SecurityValidator.sanitize_display_text('<iframe src="foo"></iframe>', "desc")
    # Should match closing tag
    with pytest.raises(ValueError):
        SecurityValidator.sanitize_display_text("</script>", "desc")
    # Should match <meta> tag
    with pytest.raises(ValueError):
        SecurityValidator.sanitize_display_text("<meta>", "desc")


def test_sanitize_display_text_js(patch_logger):
    # Should match javascript: pattern
    with pytest.raises(ValueError):
        SecurityValidator.sanitize_display_text("javascript:alert(1)", "desc")
    # Should match vbscript: pattern
    with pytest.raises(ValueError):
        SecurityValidator.sanitize_display_text("vbscript:foo()", "desc")
    # Should match onload= pattern
    with pytest.raises(ValueError):
        SecurityValidator.sanitize_display_text("<img src=x onload=alert(1)>", "desc")
    # Should match data:script pattern
    with pytest.raises(ValueError):
        SecurityValidator.sanitize_display_text("data:text/html;script", "desc")


def test_validate_name_valid():
    assert SecurityValidator.validate_name("ValidName", "Name") == "ValidName"


def test_validate_name_empty():
    with pytest.raises(ValueError):
        SecurityValidator.validate_name("", "Name")


def test_validate_name_special_chars():
    with pytest.raises(ValueError):
        SecurityValidator.validate_name("bad<name>", "Name")


def test_validate_name_too_long():
    # MAX_NAME_LENGTH = 10, so 11 chars should fail
    with pytest.raises(ValueError):
        SecurityValidator.validate_name("a" * 11, "Name")
    # 10 chars should pass
    SecurityValidator.validate_name("a" * 10, "Name")


def test_validate_identifier_valid():
    assert SecurityValidator.validate_identifier("id_1.2", "ID") == "id_1.2"


def test_validate_identifier_empty():
    with pytest.raises(ValueError):
        SecurityValidator.validate_identifier("", "ID")


def test_validate_identifier_html():
    with pytest.raises(ValueError):
        SecurityValidator.validate_identifier("bad<id>", "ID")


def test_validate_identifier_too_long():
    with pytest.raises(ValueError):
        SecurityValidator.validate_identifier("a" * 11, "ID")
    SecurityValidator.validate_identifier("a" * 10, "ID")


def test_validate_uri_valid():
    # Use a URI under 50 chars
    uri = "abc://foo/bar"
    with pytest.raises(ValueError):
        SecurityValidator.validate_uri(uri, "URI")


def test_validate_uri_empty():
    with pytest.raises(ValueError):
        SecurityValidator.validate_uri("", "URI")


def test_validate_uri_html():
    with pytest.raises(ValueError):
        SecurityValidator.validate_uri("bad<uri>", "URI")


def test_validate_uri_traversal():
    with pytest.raises(ValueError):
        SecurityValidator.validate_uri("foo/../bar", "URI")


def test_validate_uri_invalid_chars():
    with pytest.raises(ValueError):
        SecurityValidator.validate_uri("foo|bar", "URI")


def test_validate_uri_too_long():
    with pytest.raises(ValueError):
        SecurityValidator.validate_uri("a" * 11, "URI")
    SecurityValidator.validate_uri("a" * 10, "URI")


def test_validate_tool_name_valid():
    assert SecurityValidator.validate_tool_name("Tool_1") == "Tool_1"


def test_validate_tool_name_empty():
    with pytest.raises(ValueError):
        SecurityValidator.validate_tool_name("")


def test_validate_tool_name_invalid():
    with pytest.raises(ValueError):
        SecurityValidator.validate_tool_name("1bad")


def test_validate_tool_name_html():
    with pytest.raises(ValueError):
        SecurityValidator.validate_tool_name("bad<tool>")


def test_validate_tool_name_too_long():
    with pytest.raises(ValueError):
        SecurityValidator.validate_tool_name("a" * 11)
    SecurityValidator.validate_tool_name("a" * 10)


def test_validate_template_valid():
    assert SecurityValidator.validate_template("Hello {{ name }}") == "Hello {{ name }}"


def test_validate_template_too_long():
    with pytest.raises(ValueError):
        SecurityValidator.validate_template("a" * 101)
    SecurityValidator.validate_template("a" * 100)


def test_validate_template_dangerous_tag():
    with pytest.raises(ValueError):
        SecurityValidator.validate_template("<script>alert(1)</script>")


def test_validate_template_event_handler():
    with pytest.raises(ValueError):
        SecurityValidator.validate_template("<div onclick=alert(1)>")


def test_validate_url_valid():
    assert SecurityValidator.validate_url("https://foo.com", "URL") == "https://foo.com"


def test_validate_url_empty():
    with pytest.raises(ValueError):
        SecurityValidator.validate_url("", "URL")


def test_validate_url_too_long():
    # 50 is max, so 51 should fail
    with pytest.raises(ValueError):
        SecurityValidator.validate_url("http://" + "a" * 44, "URL")
    SecurityValidator.validate_url("http://" + "a" * 43, "URL")


def test_validate_url_bad_scheme():
    with pytest.raises(ValueError):
        SecurityValidator.validate_url("ftp://foo.com", "URL")


def test_validate_url_dangerous_protocol():
    with pytest.raises(ValueError):
        SecurityValidator.validate_url("javascript:alert(1)", "URL")
    with pytest.raises(ValueError):
        SecurityValidator.validate_url("data:text/html;base64,SGVsbG8=", "URL")
    with pytest.raises(ValueError):
        SecurityValidator.validate_url("vbscript:foo()", "URL")
    with pytest.raises(ValueError):
        SecurityValidator.validate_url("about:blank", "URL")
    with pytest.raises(ValueError):
        SecurityValidator.validate_url("chrome://settings", "URL")
    with pytest.raises(ValueError):
        SecurityValidator.validate_url("file:///etc/passwd", "URL")
    with pytest.raises(ValueError):
        SecurityValidator.validate_url("ftp://foo.com", "URL")
    with pytest.raises(ValueError):
        SecurityValidator.validate_url("mailto:foo@bar.com", "URL")
