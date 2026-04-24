# -*- coding: utf-8 -*-
"""Unit tests for malicious pattern detection (US-3)

Tests the ContentSecurityService.detect_malicious_patterns method
to verify XSS, command injection, SQL injection, and template injection detection.
"""

# Standard
from unittest.mock import patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.content_security import ContentPatternError, ContentSecurityService


class TestMaliciousPatternDetection:
    """Test malicious pattern detection in ContentSecurityService."""

    def test_detect_xss_script_tag(self):
        """Test detection of <script> tags."""
        service = ContentSecurityService()

        with pytest.raises(ContentPatternError) as exc_info:
            service.detect_malicious_patterns(content="Hello <script>alert('XSS')</script> World", content_type="Resource content")

        assert exc_info.value.violation_type == "xss"
        assert exc_info.value.content_type == "Resource content"

    def test_detect_xss_javascript_protocol(self):
        """Test detection of javascript: protocol."""
        service = ContentSecurityService()

        with pytest.raises(ContentPatternError) as exc_info:
            service.detect_malicious_patterns(content='<a href="javascript:alert(1)">Click</a>', content_type="Resource content")

        assert exc_info.value.violation_type == "xss"

    def test_detect_xss_event_handler(self):
        """Test detection of event handlers."""
        service = ContentSecurityService()

        with pytest.raises(ContentPatternError) as exc_info:
            service.detect_malicious_patterns(content='<img src="x" onerror="alert(1)">', content_type="Resource content")

        assert exc_info.value.violation_type == "xss"

    def test_detect_command_injection_semicolon(self):
        """Test detection of command injection with semicolon."""
        service = ContentSecurityService()

        with pytest.raises(ContentPatternError) as exc_info:
            service.detect_malicious_patterns(content="Run: ls -la; rm -rf /", content_type="Resource content")

        assert exc_info.value.violation_type == "command_injection"

    def test_detect_command_injection_chaining(self):
        """Test detection of command chaining with &&."""
        service = ContentSecurityService()

        with pytest.raises(ContentPatternError) as exc_info:
            service.detect_malicious_patterns(content="echo hello && cat /etc/passwd", content_type="Resource content")

        assert exc_info.value.violation_type == "command_injection"

    def test_detect_command_injection_backticks(self):
        """Test detection of backtick command execution."""
        service = ContentSecurityService()

        with pytest.raises(ContentPatternError) as exc_info:
            service.detect_malicious_patterns(content="Output: `whoami`", content_type="Resource content")

        assert exc_info.value.violation_type == "command_injection"

    def test_detect_sql_injection_keywords(self):
        """Test detection of SQL keywords."""
        service = ContentSecurityService()

        with pytest.raises(ContentPatternError) as exc_info:
            service.detect_malicious_patterns(content="Query: SELECT * FROM users WHERE id=1", content_type="Resource content")

        assert exc_info.value.violation_type == "sql_injection"

    def test_detect_sql_injection_comment(self):
        """Test detection of SQL comment injection."""
        service = ContentSecurityService()

        with pytest.raises(ContentPatternError) as exc_info:
            service.detect_malicious_patterns(content="Input: admin'-- ", content_type="Resource content")

        assert exc_info.value.violation_type == "sql_injection"

    def test_detect_template_injection_jinja(self):
        """Test detection of Jinja2 template injection."""
        service = ContentSecurityService()

        with pytest.raises(ContentPatternError) as exc_info:
            service.detect_malicious_patterns(content="User input: {{ config.items() }}", content_type="Resource content")

        assert exc_info.value.violation_type == "template_injection"

    def test_detect_template_injection_expression(self):
        """Test detection of ${} expression injection."""
        service = ContentSecurityService()

        with pytest.raises(ContentPatternError) as exc_info:
            service.detect_malicious_patterns(content="Value: ${7*7}", content_type="Resource content")

        assert exc_info.value.violation_type == "template_injection"

    def test_clean_content_allowed(self):
        """Test that clean content passes validation."""
        service = ContentSecurityService()

        # Should not raise
        service.detect_malicious_patterns(content="This is clean content with no malicious patterns", content_type="Resource content")

    def test_lenient_mode_allows_malicious_content(self):
        """Test that lenient mode logs but allows malicious content."""
        with patch("mcpgateway.services.content_security.settings") as mock_settings:
            mock_settings.content_pattern_detection_enabled = True
            mock_settings.content_pattern_validation_mode = "lenient"
            mock_settings.content_blocked_patterns = [r"<script[^>]*>.*?</script>"]
            mock_settings.content_blocked_template_patterns = []
            mock_settings.content_pattern_max_scan_size = 1_000_000
            mock_settings.content_pattern_regex_timeout = 1.0

            service = ContentSecurityService()

            # Should not raise in lenient mode
            service.detect_malicious_patterns(content="<script>alert('XSS')</script>", content_type="Resource content")

    def test_lenient_mode_logs_all_co_occurring_violations(self, caplog):
        """Regression: lenient mode must scan every pattern, not stop at the first match."""
        # Standard
        import logging

        with patch("mcpgateway.services.content_security.settings") as mock_settings:
            mock_settings.content_pattern_detection_enabled = True
            mock_settings.content_pattern_validation_mode = "lenient"
            mock_settings.content_blocked_patterns = [
                r"<script[^>]*>.*?</script>",
                r"(?i)(union|select|insert|update|delete|drop)\s+",
                r"&&|\|\|",
            ]
            mock_settings.content_blocked_template_patterns = []
            mock_settings.content_pattern_max_scan_size = 1_000_000
            mock_settings.content_pattern_regex_timeout = 1.0

            service = ContentSecurityService()

            with caplog.at_level(logging.INFO, logger="mcpgateway.services.content_security"):
                service.detect_malicious_patterns(
                    content="<script>alert(1)</script> SELECT * FROM users && rm -rf /",
                    content_type="Resource content",
                )

            allowed_messages = [r.message for r in caplog.records if r.message.startswith("Lenient mode: allowing")]
            assert len(allowed_messages) >= 3, f"Expected 3 co-occurring violations to be logged, got {len(allowed_messages)}: {allowed_messages}"

    def test_disabled_detection_allows_all(self):
        """Test that disabled detection allows all content."""
        service = ContentSecurityService()

        with patch("mcpgateway.services.content_security.settings") as mock_settings:
            mock_settings.content_pattern_detection_enabled = False

            # Should not raise when disabled
            service.detect_malicious_patterns(content="<script>alert('XSS')</script>", content_type="Resource content")

    def test_pattern_matched_truncated(self):
        """Test that pattern_matched is truncated for security."""
        service = ContentSecurityService()

        long_script = "<script>" + "A" * 100 + "</script>"

        with pytest.raises(ContentPatternError) as exc_info:
            service.detect_malicious_patterns(content=long_script, content_type="Resource content")

        # pattern_matched should be truncated to 50 chars
        assert len(exc_info.value.pattern_matched) <= 50

    def test_content_snippet_provided(self):
        """Test that content snippet is provided with context."""
        service = ContentSecurityService()

        with pytest.raises(ContentPatternError) as exc_info:
            service.detect_malicious_patterns(content="Before text <script>alert('XSS')</script> After text", content_type="Resource content")

        # Should have content snippet with context
        assert exc_info.value.content_snippet is not None
        assert "Before" in exc_info.value.content_snippet or "After" in exc_info.value.content_snippet


class TestClassifyViolation:
    """Test violation type classification."""

    def test_classify_xss_script(self):
        """Test classification of script tag as XSS."""
        service = ContentSecurityService()
        result = service._classify_violation(pattern=r"<script", matched_text="<script>alert(1)</script>")
        assert result == "xss"

    def test_classify_xss_javascript(self):
        """Test classification of javascript: as XSS."""
        service = ContentSecurityService()
        result = service._classify_violation(pattern=r"javascript:", matched_text="javascript:alert(1)")
        assert result == "xss"

    def test_classify_command_injection(self):
        """Test classification of command injection."""
        service = ContentSecurityService()
        result = service._classify_violation(pattern=r"&&", matched_text="ls && rm -rf /")
        assert result == "command_injection"

    def test_classify_sql_injection(self):
        """Test classification of SQL injection."""
        service = ContentSecurityService()
        result = service._classify_violation(pattern=r"SELECT", matched_text="SELECT * FROM users")
        assert result == "sql_injection"

    def test_classify_template_injection(self):
        """Test classification of template injection."""
        service = ContentSecurityService()
        result = service._classify_violation(pattern=r"\{\{", matched_text="{{ config.items() }}")
        assert result == "template_injection"

    def test_classify_unknown(self):
        """Test classification of unknown pattern."""
        service = ContentSecurityService()
        result = service._classify_violation(pattern=r"unknown", matched_text="unknown pattern")
        assert result == "unknown"


class TestTimeoutAndEdgeCases:
    """Test timeout handling and edge cases for coverage."""

    def test_timeout_error_handling(self):
        """Test TimeoutError is caught and converted to ContentPatternError."""
        service = ContentSecurityService()

        # Force the thread-based fallback path (Py<3.13 semantics) regardless of
        # the interpreter the tests are running on, then make that helper raise.
        with patch("mcpgateway.services.content_security._HAS_NATIVE_REGEX_TIMEOUT", False), patch.object(service, "_regex_search_with_timeout", side_effect=TimeoutError("Pattern timeout")):
            with pytest.raises(ContentPatternError) as exc_info:
                service.detect_malicious_patterns(content="test content", content_type="Test content")

            assert exc_info.value.violation_type == "redos_timeout"
            assert exc_info.value.pattern_matched == "[timeout]"

    def test_fallback_path_no_match(self):
        """Test fallback path when no patterns match (covers line 514 fallback)."""
        service = ContentSecurityService()

        # Clean content should not raise - tests the no-match path
        service.detect_malicious_patterns(content="Hello world, this is clean content", content_type="Test")
        # If we get here, the fallback path worked (no exception)

    def test_lenient_mode_return_path(self):
        """Test lenient mode allows malicious content and returns early."""
        with patch("mcpgateway.services.content_security.settings") as mock_settings:
            mock_settings.content_pattern_detection_enabled = True
            mock_settings.content_pattern_validation_mode = "lenient"
            mock_settings.content_blocked_patterns = [r"<script"]
            mock_settings.content_blocked_template_patterns = []
            mock_settings.content_pattern_max_scan_size = 1_000_000
            mock_settings.content_pattern_regex_timeout = 1.0

            service = ContentSecurityService()

            # Should NOT raise in lenient mode
            service.detect_malicious_patterns(content="<script>alert(1)</script>", content_type="Test")
            # If we get here without exception, lenient mode worked

    def test_python313_native_timeout_path_coverage(self):
        """Cover the Python 3.13+ native `compiled.search(..., timeout=)` branch.

        Stubs the compiled pattern list with a mock whose ``.search`` accepts the
        timeout kwarg (real re.Pattern.search rejects it on Py<3.13), forces the
        module-level ``_HAS_NATIVE_REGEX_TIMEOUT`` constant True, and asserts the
        thread-based fallback helper is not invoked.
        """
        # Standard
        from unittest.mock import MagicMock

        service = ContentSecurityService()
        mock_compiled = MagicMock()
        mock_compiled.search.return_value = None

        with (
            patch("mcpgateway.services.content_security._HAS_NATIVE_REGEX_TIMEOUT", True),
            patch.object(service, "_compiled_blocked_patterns", [("test_pattern", mock_compiled)]),
            patch.object(service, "_regex_search_with_timeout") as mock_fallback,
        ):
            service.detect_malicious_patterns(content="Clean content", content_type="Test")
            assert not mock_fallback.called, "Py3.13+ path incorrectly fell back to thread-based timeout"
            mock_compiled.search.assert_called_once_with("Clean content", timeout=1.0)
