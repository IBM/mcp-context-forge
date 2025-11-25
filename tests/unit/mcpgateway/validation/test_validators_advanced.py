# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/validation/test_validators_advanced.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Test the validators module.
Author: Mihai Criveti

This module provides comprehensive tests for the SecurityValidator class,
including validation of names, identifiers, URIs, URLs, templates, and
dangerous content patterns (HTML/JavaScript).

The tests cover:
- Basic validation rules (empty values, length limits, character restrictions)
- XSS prevention (HTML tags, JavaScript patterns, event handlers)
- Case sensitivity handling
- Boundary detection for security patterns
- False positive prevention for legitimate content
- URL scheme validation and dangerous protocol detection
"""

# Standard
from unittest.mock import patch

# Third-Party
import pytest

# First-Party
from mcpgateway.common.validators import SecurityValidator


class DummySettings:
    """Mock settings for testing SecurityValidator.

    These settings define validation patterns and limits used throughout
    the tests. The patterns are designed to catch common XSS vectors while
    minimizing false positives.
    """

    # HTML pattern: Catches dangerous HTML tags that could be used for XSS
    validation_dangerous_html_pattern = (
        r"<(script|iframe|object|embed|link|meta|base|form|img|svg|video|audio|source|track|"
        r"area|map|canvas|applet|frame|frameset|html|head|body|style)\b|"
        r"</*(script|iframe|object|embed|link|meta|base|form|img|svg|video|audio|source|track|"
        r"area|map|canvas|applet|frame|frameset|html|head|body|style)>"
    )

    # JavaScript pattern: Enhanced pattern with case-insensitive matching and boundary detection
    # This is the NEW pattern being tested
    validation_dangerous_js_pattern = r"(?i)(?:^|\s|[\"'`<>=])(javascript:|vbscript:|data:\s*[^,]*[;\s]*(javascript|vbscript)|" r"\bon[a-z]+\s*=|<\s*script\b)"

    # Allowed URL schemes for security
    validation_allowed_url_schemes = ["http://", "https://", "ws://", "wss://"]

    # Character validation patterns
    validation_name_pattern = r"^[a-zA-Z0-9_.\-\s]+$"  # Names can have spaces
    validation_identifier_pattern = r"^[a-zA-Z0-9_\-\.]+$"  # IDs cannot have spaces
    validation_safe_uri_pattern = r"^[a-zA-Z0-9_\-.:/?=&%{}]+$"
    validation_unsafe_uri_pattern = r'[<>"\'\\]'
    validation_tool_name_pattern = r"^[a-zA-Z][a-zA-Z0-9._-]*$"  # Must start with letter

    # Size limits for various fields
    validation_max_name_length = 100  # Realistic name length
    validation_max_description_length = 1000
    validation_max_template_length = 10000
    validation_max_content_length = 100000
    validation_max_json_depth = 5
    validation_max_url_length = 2048  # Standard URL length limit

    # Allowed MIME types
    validation_allowed_mime_types = ["application/json", "text/plain", "text/html"]


@pytest.fixture(autouse=True)
def patch_logger(monkeypatch):
    """Mock logger to capture log messages during tests."""
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
    """Patch settings and SecurityValidator class variables for testing."""
    with patch("mcpgateway.config.settings", new=DummySettings):
        # Update all class variables to use test settings
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


# =============================================================================
# SANITIZE DISPLAY TEXT TESTS
# =============================================================================


def test_sanitize_display_text_valid():
    """Test that valid text passes through with HTML escaping."""
    # Normal text should be escaped but not raise errors
    result = SecurityValidator.sanitize_display_text("Hello World", "desc")
    assert result == "Hello World"

    # Text with special characters should be escaped
    result = SecurityValidator.sanitize_display_text("Hello & Goodbye", "desc")
    assert result == "Hello &amp; Goodbye"

    # Quotes should be escaped
    result = SecurityValidator.sanitize_display_text('Hello "World"', "desc")
    assert result == "Hello &quot;World&quot;"


def test_sanitize_display_text_empty():
    """Test that empty strings are handled correctly."""
    assert SecurityValidator.sanitize_display_text("", "desc") == ""
    assert SecurityValidator.sanitize_display_text(None, "desc") == None


def test_sanitize_display_text_html_tags():
    """Test detection of dangerous HTML tags."""
    dangerous_html = [
        "<script>alert(1)</script>",
        '<iframe src="malicious.com"></iframe>',
        "<object data='bad.swf'></object>",
        "<embed src='bad.swf'>",
        "<link rel='stylesheet' href='bad.css'>",
        "<meta http-equiv='refresh' content='0;url=bad.com'>",
        "<base href='http://evil.com/'>",
        "<form action='steal.php'>",
        "</script>",  # Closing tags also caught
        "<img src=x onerror=alert(1)>",
        "<svg onload=alert(1)>",
        "<style>@import 'bad.css';</style>",
    ]

    for html in dangerous_html:
        with pytest.raises(ValueError, match="contains HTML tags"):
            SecurityValidator.sanitize_display_text(html, "desc")


def test_sanitize_display_text_js_patterns_basic():
    """Test detection of basic JavaScript patterns."""
    # Only test patterns that won't be caught by HTML filter first
    dangerous_js = [
        " javascript:alert(1)",  # Space before to trigger boundary
        " vbscript:msgbox(1)",  # Space before to trigger boundary
        " data:text/html;javascript",  # Space before to trigger boundary
    ]

    for js in dangerous_js:
        with pytest.raises(ValueError, match="contains script patterns"):
            SecurityValidator.sanitize_display_text(js, "desc")

    # These contain both HTML and JS patterns - JS pattern might be checked first
    mixed_patterns = [
        "<img src=x onload=alert(1)>",
        "<div onclick=alert(1)>",
    ]

    for pattern in mixed_patterns:
        with pytest.raises(ValueError, match="contains (HTML tags|script patterns)"):
            SecurityValidator.sanitize_display_text(pattern, "desc")


def test_sanitize_display_text_js_case_insensitive():
    """Test that JavaScript patterns are caught regardless of case."""
    # Pure JS patterns (no HTML tags)
    case_variations = [
        "JavaScript:alert(1)",
        "JAVASCRIPT:alert(1)",
        "JaVaScRiPt:alert(1)",
        "VBScript:msgbox(1)",
        "vBsCrIpT:msgbox(1)",
        "VBSCRIPT:msgbox(1)",
    ]

    for js in case_variations:
        with pytest.raises(ValueError, match="contains script patterns"):
            SecurityValidator.sanitize_display_text(js, "desc")

    # These contain HTML tags so will be caught by HTML filter
    html_case_variations = [
        "<img src=x OnLoad=alert(1)>",
        "<img src=x ONLOAD=alert(1)>",
        "<img src=x oNcLiCk=alert(1)>",
    ]

    for html in html_case_variations:
        with pytest.raises(ValueError, match="contains HTML tags"):
            SecurityValidator.sanitize_display_text(html, "desc")


def test_sanitize_display_text_js_boundaries():
    """Test boundary detection for JavaScript patterns."""
    # Should catch with various delimiters
    boundary_cases = [
        '"javascript:alert(1)"',  # Double quotes
        "'javascript:alert(1)'",  # Single quotes
        "`javascript:alert(1)`",  # Backticks
        "<javascript:alert(1)>",  # Angle brackets
        "=javascript:alert(1)",  # Equals sign
        " javascript:alert(1)",  # Space before
    ]

    for js in boundary_cases:
        with pytest.raises(ValueError, match="contains script patterns"):
            SecurityValidator.sanitize_display_text(js, "desc")

    # Should NOT catch when part of a word (no boundary)
    valid_cases = [
        "myjavascript:function",  # Part of larger word
        "nojavascript:here",  # Part of larger word
    ]

    for valid in valid_cases:
        # These should pass through (though will be HTML escaped)
        result = SecurityValidator.sanitize_display_text(valid, "desc")
        assert "javascript:" in result.lower()  # Verify it wasn't blocked


@pytest.mark.skip(reason="test_sanitize_display_text_data_uri_enhanced not implemented")
def test_sanitize_display_text_data_uri_enhanced():
    """Test enhanced data URI detection."""
    # Should catch data URIs with script execution
    dangerous_data_uris = [
        " data:text/html;javascript",  # Space before to trigger boundary
        " data:text/html;base64,javascript",  # Space before
        " data:;javascript",  # Space before
        " data: text/html ; javascript",  # With spaces and boundary
        " data:text/html;vbscript",  # Space before
        " data: ; vbscript",  # Space before
    ]

    for uri in dangerous_data_uris:
        with pytest.raises(ValueError, match="contains script patterns"):
            SecurityValidator.sanitize_display_text(uri, "desc")

    # Should NOT catch legitimate data URIs without script execution
    valid_data_uris = [
        "data:image/png;base64,iVBORw0KGgo",
        "data:text/plain;charset=utf-8,Hello%20World",
        "data:image/jpeg;base64,/9j/4AAQSkZJRg",
        "data:application/x-javascript",  # Without actual javascript/vbscript after semicolon
    ]

    for uri in valid_data_uris:
        result = SecurityValidator.sanitize_display_text(uri, "desc")
        assert "data:" in result  # Verify it wasn't blocked


def test_sanitize_display_text_event_handlers_precise():
    """Test precise event handler detection with word boundaries."""
    # Should catch actual event handlers (pure, without HTML tags)
    event_handlers = [
        " onclick=alert(1)",  # Space before to trigger boundary
        " onmouseover=alert(1)",
        " onload=doEvil()",
        " onerror=hack()",
    ]

    for handler in event_handlers:
        with pytest.raises(ValueError, match="contains script patterns"):
            SecurityValidator.sanitize_display_text(handler, "desc")

    # HTML-containing event handlers might be caught by either filter
    with pytest.raises(ValueError, match="contains (HTML tags|script patterns)"):
        SecurityValidator.sanitize_display_text('<div onkeydown="steal()">', "desc")

    # Should NOT catch words that happen to start with 'on' when not preceded by boundary
    # Note: Some patterns like "once=", "only=", "online=" will be caught because they match \bon[a-z]+\s*=
    false_positive_cases = [
        "conditional=true",  # Should pass - doesn't start with 'on'
        "donation=100",  # Should pass - doesn't start with 'on'
        "honor=high",  # Should pass - doesn't start with 'on'
    ]

    for valid in false_positive_cases:
        result = SecurityValidator.sanitize_display_text(valid, "desc")
        assert valid.split("=")[0] in result  # Verify the word wasn't blocked


def test_sanitize_display_text_script_tag_variations():
    """Test script tag detection with whitespace variations."""
    # These will be caught by HTML pattern, not JS pattern
    script_variations = [
        "< script>alert(1)</script>",  # Space after <
        "<  script>alert(1)</script>",  # Multiple spaces
        "<\tscript>alert(1)</script>",  # Tab
        "<\nscript>alert(1)</script>",  # Newline
        "< \tscript>alert(1)</script>",  # Mixed whitespace
    ]

    for script in script_variations:
        with pytest.raises(ValueError, match="contains HTML tags"):
            SecurityValidator.sanitize_display_text(script, "desc")


@pytest.mark.skip(reason="test_sanitize_display_text_false_positives not implemented")
def test_sanitize_display_text_false_positives():
    """Test that legitimate content is not incorrectly blocked."""
    # The new pattern will catch some of these, so we need to adjust expectations
    legitimate_content = [
        # These should actually pass
        "Learn about JavaScript programming at our school",  # JavaScript (capital S) without colon
        "The conditional=false setting disables checks",
        "The function uses data: {name: 'value'} format",  # data: without javascript/vbscript
        "We accept donations online",
        "Check your internet connection if you're not online",
        "This is done only once per session",
    ]

    for content in legitimate_content:
        try:
            result = SecurityValidator.sanitize_display_text(content, "desc")
            # Should succeed and return escaped content
            assert result is not None
        except ValueError as e:
            pytest.fail(f"False positive - legitimate content blocked: '{content}' - Error: {e}")

    # These are expected to be caught due to the new pattern's boundary detection
    expected_catches = [
        " javascript: protocol is dangerous",  # Space before javascript:
        " online=true to enable",  # Space before online= matches pattern
        " data: text/html ; javascript",  # data: followed by javascript
        " onclick handlers can be risky",  # Space before onclick
        " once=true for single",  # Space before once=
        " only=false to disable",  # Space before only=
    ]

    for content in expected_catches:
        with pytest.raises(ValueError, match="contains script patterns"):
            SecurityValidator.sanitize_display_text(content, "desc")


# =============================================================================
# NAME VALIDATION TESTS
# =============================================================================


def test_validate_name_valid():
    """Test valid name patterns."""
    valid_names = [
        "ValidName",
        "Valid Name",  # Spaces allowed
        "Valid.Name",  # Dots allowed
        "Valid-Name",  # Hyphens allowed
        "Valid_Name",  # Underscores allowed
        "Name123",  # Numbers allowed
        "A",  # Single character
    ]

    for name in valid_names:
        assert SecurityValidator.validate_name(name, "Name") == name


def test_validate_name_invalid():
    """Test invalid name patterns."""
    with pytest.raises(ValueError, match="cannot be empty"):
        SecurityValidator.validate_name("", "Name")

    # Special characters not allowed - check for actual error message
    invalid_chars = ["Name!", "Name@", "Name#", "Name$", "Name%", "Name<>", "Name&"]
    for name in invalid_chars:
        with pytest.raises(ValueError, match="can only contain letters, numbers"):
            SecurityValidator.validate_name(name, "Name")


def test_validate_name_length():
    """Test name length validation."""
    # At limit (100 chars)
    valid_name = "a" * 100
    assert SecurityValidator.validate_name(valid_name, "Name") == valid_name

    # Over limit (101 chars)
    with pytest.raises(ValueError, match="exceeds maximum length"):
        SecurityValidator.validate_name("a" * 101, "Name")


# =============================================================================
# IDENTIFIER VALIDATION TESTS
# =============================================================================


def test_validate_identifier_valid():
    """Test valid identifier patterns."""
    valid_ids = [
        "id123",
        "user_id",
        "user-id",
        "user.id",
        "UUID.123.456",
        "a",  # Single character
    ]

    for id_val in valid_ids:
        assert SecurityValidator.validate_identifier(id_val, "ID") == id_val


def test_validate_identifier_invalid():
    """Test invalid identifier patterns."""
    with pytest.raises(ValueError, match="cannot be empty"):
        SecurityValidator.validate_identifier("", "ID")

    # No spaces allowed in identifiers - check for actual error message
    with pytest.raises(ValueError, match="can only contain letters, numbers"):
        SecurityValidator.validate_identifier("id with space", "ID")

    # No special characters
    invalid_ids = ["id!", "id@", "id#", "id<>", "id&"]
    for id_val in invalid_ids:
        with pytest.raises(ValueError, match="can only contain letters, numbers"):
            SecurityValidator.validate_identifier(id_val, "ID")


def test_validate_identifier_length():
    """Test identifier length validation."""
    # At limit
    valid_id = "a" * 100
    assert SecurityValidator.validate_identifier(valid_id, "ID") == valid_id

    # Over limit
    with pytest.raises(ValueError, match="exceeds maximum length"):
        SecurityValidator.validate_identifier("a" * 101, "ID")


# =============================================================================
# URI VALIDATION TESTS
# =============================================================================


def test_validate_uri_patterns():
    """Test URI validation patterns."""
    # URIs must match safe pattern
    valid_uri = "http://example.com/path"
    result = SecurityValidator.validate_uri(valid_uri, "URI")
    assert result == valid_uri

    # Empty URI
    with pytest.raises(ValueError, match="cannot be empty"):
        SecurityValidator.validate_uri("", "URI")

    # Path traversal - check for actual error message
    with pytest.raises(ValueError, match="cannot contain directory traversal"):
        SecurityValidator.validate_uri("../../../etc/passwd", "URI")

    # HTML in URI
    with pytest.raises(ValueError, match="cannot contain HTML"):
        SecurityValidator.validate_uri("path/<script>", "URI")

    # Invalid characters
    with pytest.raises(ValueError, match="contains invalid characters"):
        SecurityValidator.validate_uri("path|with|pipes", "URI")


# =============================================================================
# TOOL NAME VALIDATION TESTS
# =============================================================================


def test_validate_tool_name_valid():
    """Test valid tool name patterns."""
    valid_names = [
        "tool",
        "Tool",
        "tool_name",
        "tool-name",
        "tool.name",
        "toolName123",
        "t",  # Single character
    ]

    for name in valid_names:
        assert SecurityValidator.validate_tool_name(name) == name


def test_validate_tool_name_invalid():
    """Test invalid tool name patterns."""
    # Empty name
    with pytest.raises(ValueError, match="cannot be empty"):
        SecurityValidator.validate_tool_name("")

    # Must start with letter - check actual error message
    with pytest.raises(ValueError, match="must start with a letter"):
        SecurityValidator.validate_tool_name("1tool")
    with pytest.raises(ValueError, match="must start with a letter"):
        SecurityValidator.validate_tool_name("_tool")
    with pytest.raises(ValueError, match="must start with a letter"):
        SecurityValidator.validate_tool_name("-tool")

    # Tool name pattern doesn't match - check actual error
    with pytest.raises(ValueError, match="must start with a letter"):
        SecurityValidator.validate_tool_name("tool<name>")
    with pytest.raises(ValueError, match="must start with a letter"):
        SecurityValidator.validate_tool_name('tool"name')


def test_validate_tool_name_length():
    """Test tool name length validation."""
    # At limit
    valid_name = "t" + "o" * 99  # 100 chars total, starts with letter
    assert SecurityValidator.validate_tool_name(valid_name) == valid_name

    # Over limit
    with pytest.raises(ValueError, match="exceeds maximum length"):
        SecurityValidator.validate_tool_name("t" + "o" * 100)  # 101 chars


# =============================================================================
# TEMPLATE VALIDATION TESTS
# =============================================================================


def test_validate_template_valid():
    """Test valid template patterns."""
    valid_templates = [
        "Hello {{ name }}",  # Jinja2 variable
        "{% if condition %}Show this{% endif %}",  # Jinja2 control
        "Plain text template",
        "<div>{{ content }}</div>",  # HTML with Jinja2
        "",  # Empty template
    ]

    for template in valid_templates:
        assert SecurityValidator.validate_template(template) == template


def test_validate_template_dangerous():
    """Test detection of dangerous content in templates."""
    # Dangerous HTML tags
    dangerous_templates = [
        "<script>alert(1)</script>",
        "<iframe src='bad.com'></iframe>",
        "<form action='steal.php'>",
        "<embed src='bad.swf'>",
    ]

    for template in dangerous_templates:
        with pytest.raises(ValueError, match="contains HTML tags"):
            SecurityValidator.validate_template(template)

    # Event handlers
    with pytest.raises(ValueError, match="contains event handlers"):
        SecurityValidator.validate_template("<div onclick='alert(1)'>")


def test_validate_template_length():
    """Test template length validation."""
    # At limit (10000 chars)
    valid_template = "a" * 10000
    assert SecurityValidator.validate_template(valid_template) == valid_template

    # Over limit
    with pytest.raises(ValueError, match="exceeds maximum length"):
        SecurityValidator.validate_template("a" * 10001)


# =============================================================================
# URL VALIDATION TESTS
# =============================================================================


def test_validate_url_valid():
    """Test valid URL patterns."""
    valid_urls = [
        "http://example.com",
        "https://example.com",
        "https://example.com/path",
        "https://example.com:8080/path?query=value",
        "ws://websocket.example.com",
        "wss://secure-websocket.example.com",
    ]

    for url in valid_urls:
        assert SecurityValidator.validate_url(url, "URL") == url


def test_validate_url_invalid_schemes():
    """Test URL validation with disallowed schemes."""
    invalid_schemes = [
        "ftp://example.com",  # FTP not allowed
        "file:///etc/passwd",  # File protocol dangerous
        "javascript:alert(1)",  # JavaScript protocol
        "vbscript:msgbox(1)",  # VBScript protocol
        "data:text/html,<script>alert(1)</script>",  # Data URI
        "about:blank",  # About protocol
        "chrome://settings",  # Chrome protocol
        "mailto:user@example.com",  # Mailto protocol
    ]

    for url in invalid_schemes:
        with pytest.raises(ValueError, match="dangerous protocol|must start with"):
            SecurityValidator.validate_url(url, "URL")


def test_validate_url_case_insensitive():
    """Test that dangerous protocols are caught regardless of case."""
    case_variations = [
        "JavaScript:alert(1)",
        "JAVASCRIPT:alert(1)",
        "JaVaScRiPt:alert(1)",
        "VBScript:msgbox(1)",
        "VBSCRIPT:msgbox(1)",
        "DATA:text/html,<script>alert(1)</script>",
        "FiLe:///etc/passwd",
    ]

    for url in case_variations:
        with pytest.raises(ValueError, match="dangerous protocol|must start with"):
            SecurityValidator.validate_url(url, "URL")


def test_validate_url_structure():
    """Test URL structure validation."""
    with pytest.raises(ValueError, match="cannot be empty"):
        SecurityValidator.validate_url("", "URL")

    # Invalid URL structures
    invalid_urls = [
        "not-a-url",
        "http://",  # No host
        "://example.com",  # No scheme
        "http:/example.com",  # Missing slash
    ]

    for url in invalid_urls:
        with pytest.raises(ValueError):
            SecurityValidator.validate_url(url, "URL")


def test_validate_url_length():
    """Test URL length validation."""
    # Create a URL at the limit (2048 chars)
    long_path = "a" * (2048 - len("https://example.com/"))
    valid_url = f"https://example.com/{long_path}"
    assert SecurityValidator.validate_url(valid_url, "URL") == valid_url

    # Over limit
    with pytest.raises(ValueError, match="exceeds maximum length"):
        SecurityValidator.validate_url(valid_url + "a", "URL")


# =============================================================================
# JSON DEPTH VALIDATION TESTS
# =============================================================================


def test_validate_json_depth_valid():
    """Test JSON depth validation with valid objects."""
    # Depth 1
    obj1 = {"key": "value"}
    SecurityValidator.validate_json_depth(obj1)  # Should not raise

    # Depth 3 (at limit with default settings)
    obj3 = {"level1": {"level2": {"level3": "value"}}}
    SecurityValidator.validate_json_depth(obj3)  # Should not raise

    # Arrays count toward depth
    arr = [[[["deep"]]]]  # Depth 4 in arrays
    SecurityValidator.validate_json_depth(arr, max_depth=4)  # Should not raise


def test_validate_json_depth_exceeded():
    """Test JSON depth validation with objects exceeding max depth."""
    # Depth 6 (exceeds default limit of 5)
    deep_obj = {"l1": {"l2": {"l3": {"l4": {"l5": {"l6": "too deep"}}}}}}

    with pytest.raises(ValueError, match="exceeds maximum depth"):
        SecurityValidator.validate_json_depth(deep_obj)

    # Should work with higher limit
    SecurityValidator.validate_json_depth(deep_obj, max_depth=6)


def test_validate_json_depth_mixed():
    """Test JSON depth with mixed arrays and objects."""
    mixed = {"array": [{"nested": [{"deep": "value"}]}]}
    # Depth is 4: dict -> array -> dict -> array -> dict
    SecurityValidator.validate_json_depth(mixed, max_depth=5)  # Should not raise

    with pytest.raises(ValueError, match="exceeds maximum depth"):
        SecurityValidator.validate_json_depth(mixed, max_depth=3)


# =============================================================================
# PERFORMANCE AND EDGE CASE TESTS
# =============================================================================


@pytest.mark.parametrize(
    "test_input,should_fail",
    [
        # Legitimate content that should pass
        ("Learn JavaScript programming", False),
        ("The conditional=false setting", False),
        # TODO: Skip Use once=true for now
        # ("Use once=true", False),
        ("We accept donations online", False),
        # Dangerous content that should fail
        ("javascript:alert(1)", True),
        ("JAVASCRIPT:void(0)", True),
        ("<script>alert(1)</script>", True),
        (" onclick=hack()", True),  # Space before onclick
        # Edge cases that WILL be caught by new pattern
        ("The javascript: protocol is dangerous", True),  # Space before javascript:
        ("Set online=true", True),  # online= matches pattern
    ],
)
def test_sanitize_parametrized(test_input, should_fail):
    """Parametrized tests for various input patterns."""
    if should_fail:
        with pytest.raises(ValueError):
            SecurityValidator.sanitize_display_text(test_input, "test")
    else:
        result = SecurityValidator.sanitize_display_text(test_input, "test")
        assert result is not None


def test_pattern_performance():
    """Ensure regex patterns don't cause catastrophic backtracking."""
    # Standard
    import time

    # Create potentially problematic inputs
    test_cases = [
        "a" * 10000 + "javascript:" + "b" * 10000,  # Long string with pattern in middle
        "<" * 1000 + "script" + ">" * 1000,  # Repeated characters
        "on" * 5000 + "load=alert(1)",  # Repeated pattern prefix
    ]

    for test_input in test_cases:
        start = time.time()
        try:
            SecurityValidator.sanitize_display_text(test_input, "perf_test")
        except ValueError:
            pass  # Expected for dangerous content
        elapsed = time.time() - start

        # Should complete quickly (under 1 second even for pathological cases)
        assert elapsed < 1.0, f"Pattern took too long: {elapsed:.2f}s for input length {len(test_input)}"


def test_unicode_handling():
    """Test handling of unicode characters in validation."""
    unicode_tests = [
        "Hello 世界",  # Chinese characters
        "Привет мир",  # Cyrillic
        "مرحبا بالعالم",  # Arabic
        "🚀 Emoji test 🎉",  # Emojis
    ]

    for text in unicode_tests:
        # Should handle unicode gracefully
        result = SecurityValidator.sanitize_display_text(text, "unicode_test")
        assert result is not None

        # Name validation might be more restrictive
        with pytest.raises(ValueError, match="can only contain"):
            SecurityValidator.validate_name(text, "Name")


@pytest.mark.skip(reason="test_null_byte_injection not implemented")
def test_null_byte_injection():
    """Test handling of null byte injection attempts."""
    null_tests = [
        "javascript:\x00alert(1)",  # Null byte in middle
        "java\x00script:alert(1)",  # Null byte breaking keyword
        "<scr\x00ipt>alert(1)</script>",  # Null in tag
    ]

    for test in null_tests:
        # Should still catch these as dangerous
        with pytest.raises(ValueError):
            SecurityValidator.sanitize_display_text(test, "null_test")


# =============================================================================
# SPECIAL CASES FOR NEW PATTERN
# =============================================================================


def test_new_pattern_special_cases():
    """Test special cases specific to the new enhanced pattern."""
    # Test that the pattern requires boundaries
    assert SecurityValidator.sanitize_display_text("myjavascript:test", "desc")  # Should pass
    assert SecurityValidator.sanitize_display_text("conditional=true", "desc")  # Should pass

    # Test case insensitivity
    with pytest.raises(ValueError):
        SecurityValidator.sanitize_display_text("JAVASCRIPT:test", "desc")

    # Test data URI specifics
    with pytest.raises(ValueError):
        SecurityValidator.sanitize_display_text("data:;javascript", "desc")

    # Test that legitimate data URIs pass
    assert SecurityValidator.sanitize_display_text("data:image/png;base64,abc", "desc")
