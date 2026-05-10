# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_content_pattern_detection.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for malicious pattern detection (US-3)

Tests the ContentSecurityService.detect_malicious_patterns method
to verify XSS, command injection, SQL injection, and template injection detection.
"""

# Standard
from unittest.mock import patch

# Third-Party
import pytest

# First-Party
from mcpgateway.services.content_security import ContentPatternError, ContentSecurityService, TemplateValidationError


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
            mock_settings.content_pattern_max_cache_size = 1000
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
            mock_settings.content_pattern_max_cache_size = 1000
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

    def test_python312_clean_scan_uses_direct_compiled_regex(self):
        """Clean scans with default patterns avoid the thread-per-pattern timeout wrapper."""
        service = ContentSecurityService()

        class CountingPattern:
            """Pattern wrapper that counts direct search calls."""

            pattern = "clean"
            search_calls = 0

            def search(self, _content):
                """Count search call."""
                self.search_calls += 1

        pattern = CountingPattern()
        service._compiled_blocked_patterns = [("clean", pattern)]

        with patch.object(service, "_regex_search_with_timeout") as mock_fallback:
            mock_fallback.return_value = None
            service.detect_malicious_patterns(content="Hello world, this is clean content", content_type="Test")

        mock_fallback.assert_not_called()
        assert pattern.search_calls == 1

    def test_custom_pattern_timeout_wrapper_is_preserved(self, monkeypatch):
        """Custom operator patterns still use timeout wrapper for ReDoS safety."""
        # First-Party
        from mcpgateway.config import settings

        monkeypatch.setattr(settings, "content_blocked_patterns", [r"(a+)+$"])
        service = ContentSecurityService()

        with patch.object(service, "_regex_search_with_timeout", side_effect=TimeoutError("Pattern timeout")) as mock_timeout:
            with pytest.raises(ContentPatternError) as exc_info:
                service.detect_malicious_patterns(content="a" * 20 + "!", content_type="Test content")

        mock_timeout.assert_called_once()
        assert exc_info.value.violation_type == "redos_timeout"

    def test_clean_scan_cache_skips_repeated_regex_work(self, monkeypatch):
        """Repeated clean scans use the advertised content pattern cache."""
        # First-Party
        from mcpgateway.config import settings

        monkeypatch.setattr(settings, "content_pattern_cache_enabled", True)
        monkeypatch.setattr(settings, "content_pattern_detection_enabled", True)
        monkeypatch.setattr(settings, "content_pattern_validation_mode", "strict")

        service = ContentSecurityService()
        search_calls = 0
        original_patterns = service._compiled_blocked_patterns

        class CountingPattern:
            """Pattern wrapper that counts search calls."""

            def __init__(self, pattern):
                self.pattern = pattern.pattern
                self._pattern = pattern

            def search(self, content):
                """Count search call and delegate to wrapped pattern."""
                nonlocal search_calls
                search_calls += 1
                return self._pattern.search(content)

        service._compiled_blocked_patterns = [(raw, CountingPattern(compiled)) for raw, compiled in original_patterns]

        content = "This clean prompt is submitted repeatedly"
        service.detect_malicious_patterns(content=content, content_type="Prompt template")
        first_call_count = search_calls
        service.detect_malicious_patterns(content=content, content_type="Prompt template")

        assert first_call_count > 0
        assert search_calls == first_call_count

    def test_clean_scan_cache_is_bounded(self, monkeypatch):
        """Clean-result cache evicts old entries at its configured bound."""
        # First-Party
        from mcpgateway.config import settings

        monkeypatch.setattr(settings, "content_pattern_cache_enabled", True)
        monkeypatch.setattr(settings, "content_pattern_detection_enabled", True)
        monkeypatch.setattr(settings, "content_pattern_max_cache_size", 2)

        service = ContentSecurityService()
        assert service._clean_pattern_cache_max_entries == 2

        service.detect_malicious_patterns(content="clean content 1", content_type="Prompt template")
        service.detect_malicious_patterns(content="clean content 2", content_type="Prompt template")
        service.detect_malicious_patterns(content="clean content 3", content_type="Prompt template")

        assert len(service._clean_pattern_cache) == 2

    def test_zero_cache_size_disables_clean_scan_cache(self, monkeypatch):
        """Cache size 0 disables clean-result cache insertion."""
        # First-Party
        from mcpgateway.config import settings

        monkeypatch.setattr(settings, "content_pattern_cache_enabled", True)
        monkeypatch.setattr(settings, "content_pattern_detection_enabled", True)
        monkeypatch.setattr(settings, "content_pattern_max_cache_size", 0)

        service = ContentSecurityService()
        assert service._clean_pattern_cache_max_entries == 0

        service.detect_malicious_patterns(content="clean content", content_type="Prompt template")

        assert not service._clean_pattern_cache

    def test_malicious_content_is_not_cached(self, monkeypatch):
        """Repeated malicious scans still evaluate patterns and raise."""
        # First-Party
        from mcpgateway.config import settings

        monkeypatch.setattr(settings, "content_pattern_cache_enabled", True)
        monkeypatch.setattr(settings, "content_pattern_detection_enabled", True)
        monkeypatch.setattr(settings, "content_pattern_validation_mode", "strict")

        service = ContentSecurityService()

        for _ in range(2):
            with pytest.raises(ContentPatternError):
                service.detect_malicious_patterns(content="<script>alert(1)</script>", content_type="Resource content")

        assert not service._clean_pattern_cache

    def test_timeout_error_handling(self, monkeypatch):
        """Test TimeoutError is caught and converted to ContentPatternError."""
        # First-Party
        from mcpgateway.config import settings

        monkeypatch.setattr(settings, "content_blocked_patterns", [r"timeout"])
        service = ContentSecurityService()

        class TimeoutPattern:
            """Pattern stub that simulates regex timeout handling."""

            pattern = "timeout"

            def search(self, content):
                """Simulate regex timeout."""
                raise TimeoutError("Pattern timeout")

        with (
            patch.object(service, "_compiled_blocked_patterns", [("timeout", TimeoutPattern())]),
            patch.object(service, "_regex_search_with_timeout", side_effect=TimeoutError("Pattern timeout")),
        ):
            with pytest.raises(ContentPatternError) as exc_info:
                service.detect_malicious_patterns(content="test content", content_type="Test content")

            assert exc_info.value.violation_type == "redos_timeout"
            assert exc_info.value.pattern_matched == "[timeout]"

    def test_custom_template_pattern_timeout_wrapper_is_preserved(self, monkeypatch):
        """Custom template patterns still use timeout wrapper for ReDoS safety."""
        # First-Party
        from mcpgateway.config import settings

        monkeypatch.setattr(settings, "content_blocked_template_patterns", [r"(a+)+$"])
        service = ContentSecurityService()

        with patch.object(service, "_regex_search_with_timeout", side_effect=TimeoutError("Pattern timeout")) as mock_timeout:
            with pytest.raises(TemplateValidationError) as exc_info:
                service.validate_prompt_template(template="hello", name="timeout-test")

        mock_timeout.assert_called_once()
        assert "exceeded timeout" in str(exc_info.value)

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
            mock_settings.content_pattern_max_cache_size = 1000
            mock_settings.content_pattern_regex_timeout = 1.0

            service = ContentSecurityService()

            # Should NOT raise in lenient mode
            service.detect_malicious_patterns(content="<script>alert(1)</script>", content_type="Test")
            # If we get here without exception, lenient mode worked

    def test_search_helper_never_passes_timeout_keyword_to_stdlib_re(self):
        """The stdlib re API has no timeout keyword on supported Python versions."""
        # Standard
        import re

        service = ContentSecurityService()

        # Wrap a real compiled pattern to record calls and assert no timeout kwarg
        class SearchRecorder:
            """Proxy that records search calls and rejects unexpected kwargs."""

            def __init__(self, pattern: re.Pattern):
                self._pattern = pattern
                self.search_calls: list[tuple[tuple, dict]] = []

            def search(self, content: str, **kwargs):
                """Record call and proxy to real pattern, rejecting unexpected kwargs."""
                if kwargs:
                    raise TypeError(f"Unexpected keyword arguments: {kwargs}")
                self.search_calls.append(((content,), kwargs))
                return self._pattern.search(content)

        real_pattern = re.compile(r"clean")
        recorder = SearchRecorder(real_pattern)

        with patch.object(service, "_compiled_blocked_patterns", [("test_pattern", recorder)]), patch.object(service, "_regex_search_with_timeout") as mock_fallback:
            service.detect_malicious_patterns(content="Clean content", content_type="Test")
            assert not mock_fallback.called, "Default pattern path incorrectly fell back to thread-based timeout"
            assert len(recorder.search_calls) == 1
            assert recorder.search_calls[0][0] == ("Clean content",)
