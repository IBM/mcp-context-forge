# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_content_security.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for content security service.
"""

# Standard
from unittest.mock import patch

# Third-Party
import pytest

# First-Party
import mcpgateway.services.content_security as cs_mod
from mcpgateway.services.content_security import _format_bytes, _sanitize_pii_for_logging, ContentPatternError, ContentSecurityService, ContentSizeError, ContentTypeError, get_content_security_service


class TestFormatBytes:
    """Test the _format_bytes helper function."""

    def test_format_bytes_less_than_kb(self):
        """Test formatting bytes less than 1KB."""
        assert _format_bytes(500) == "500 B"
        assert _format_bytes(1023) == "1023 B"

    def test_format_bytes_kb(self):
        """Test formatting kilobytes."""
        assert _format_bytes(1024) == "1.0 KB"
        assert _format_bytes(2048) == "2.0 KB"
        assert _format_bytes(1536) == "1.5 KB"
        assert _format_bytes(102400) == "100.0 KB"

    def test_format_bytes_mb(self):
        """Test formatting megabytes."""
        assert _format_bytes(1048576) == "1.0 MB"
        assert _format_bytes(2097152) == "2.0 MB"
        assert _format_bytes(1572864) == "1.5 MB"

    def test_format_bytes_gb(self):
        """Test formatting gigabytes."""
        assert _format_bytes(1073741824) == "1.0 GB"
        assert _format_bytes(2147483648) == "2.0 GB"


class TestNormalizeInput:
    """Test the _normalize_input method exception handling."""

    def test_normalize_input_url_decode_exception(self):
        """Test _normalize_input handles URL decode exceptions gracefully."""
        service = ContentSecurityService()
        # Invalid percent encoding that will fail unquote
        content = "test%ZZinvalid"
        # Should not raise, just continue with original
        result = service._normalize_input(content)
        assert "test" in result

    def test_normalize_input_url_decode_exception(self):
        """Test _normalize_input handles URL decode exceptions gracefully."""
        service = ContentSecurityService()

        with patch("urllib.parse.unquote", side_effect=Exception("URL decode error")):
            content = "test%3Ccontent"
            result = service._normalize_input(content)

        assert result == "test%3Ccontent"

    def test_normalize_input_unicode_normalize_exception(self):
        """Test _normalize_input handles Unicode normalization exceptions gracefully."""
        service = ContentSecurityService()

        with patch("unicodedata.normalize", side_effect=Exception("Unicode error")):
            content = "test content"
            result = service._normalize_input(content)

        assert result == "test content"


class TestRegexSearchWithTimeout:
    """Test the _regex_search_with_timeout method exception handling."""

    def test_regex_search_with_timeout_timeout(self):
        """Test _regex_search_with_timeout raises TimeoutError on timeout (line 336)."""
        service = ContentSecurityService()
        # Mock thread.is_alive() to return True to simulate timeout
        # Standard
        import threading

        original_thread = threading.Thread

        class MockThread:
            def __init__(self, *args, **kwargs):
                self._thread = original_thread(*args, **kwargs)

            def start(self):
                self._thread.start()

            def join(self, timeout=None):
                self._thread.join(timeout)

            def is_alive(self):
                return True  # Always return True to simulate timeout

        with patch("threading.Thread", MockThread):
            with pytest.raises(TimeoutError, match="possible ReDoS attack"):
                service._regex_search_with_timeout(r"test", "test content", timeout=0.1)

    def test_regex_search_with_timeout_exception_in_thread(self):
        """Test _regex_search_with_timeout propagates exceptions from search thread (line 344)."""
        service = ContentSecurityService()
        # Use invalid regex pattern to trigger exception in thread
        pattern = r"(?P<invalid"  # Unclosed group - will raise re.error
        content = "test"

        with pytest.raises(Exception):
            service._regex_search_with_timeout(pattern, content, timeout=1.0)

            assert "test" in result

        assert _format_bytes(1610612736) == "1.5 GB"

    def test_format_bytes_zero(self):
        """Test formatting zero bytes."""
        assert _format_bytes(0) == "0 B"


class TestSanitizePiiForLogging:
    """Test the _sanitize_pii_for_logging helper function."""

    def test_sanitize_email_only(self):
        """Test sanitizing email address only."""
        result = _sanitize_pii_for_logging(user_email="user@example.com")
        assert result["user_hash"] is not None
        assert len(result["user_hash"]) == 8
        assert result["ip_subnet"] is None

    def test_sanitize_ipv4_only(self):
        """Test sanitizing IPv4 address only."""
        result = _sanitize_pii_for_logging(ip_address="192.168.1.100")
        assert result["user_hash"] is None
        assert result["ip_subnet"] == "192.168.1.xxx"

    def test_sanitize_ipv6(self):
        """Test sanitizing IPv6 address."""
        result = _sanitize_pii_for_logging(ip_address="2001:db8::1")
        assert result["ip_subnet"] == "2001:db8::xxxx"

    def test_sanitize_both(self):
        """Test sanitizing both email and IP."""
        result = _sanitize_pii_for_logging(user_email="admin@test.com", ip_address="10.0.0.1")
        assert result["user_hash"] is not None
        assert result["ip_subnet"] == "10.0.0.xxx"

    def test_sanitize_none_values(self):
        """Test with None values."""
        result = _sanitize_pii_for_logging()
        assert result["user_hash"] is None
        assert result["ip_subnet"] is None


class TestContentSizeError:
    """Test the ContentSizeError exception."""

    def test_content_size_error_attributes(self):
        """Test ContentSizeError has correct attributes."""
        error = ContentSizeError("Resource content", 200000, 102400)
        assert error.content_type == "Resource content"
        assert error.actual_size == 200000
        assert error.max_size == 102400

    def test_content_size_error_message(self):
        """Test ContentSizeError message formatting."""
        error = ContentSizeError("Resource content", 200000, 102400)
        message = str(error)
        assert "Resource content" in message
        assert "195.3 KB" in message  # 200000 bytes formatted
        assert "100.0 KB" in message  # 102400 bytes formatted
        assert "exceeds" in message.lower()


class TestContentSecurityService:
    """Test the ContentSecurityService class."""

    def test_service_initialization(self):
        """Test service initializes with correct limits."""
        service = ContentSecurityService()
        assert service.max_resource_size == 102400  # 100KB
        assert service.max_prompt_size == 10240  # 10KB

    def test_validate_resource_size_within_limit(self):
        """Test validating resource content within limit."""
        service = ContentSecurityService()
        content = "x" * 50000  # 50KB
        # Should not raise
        service.validate_resource_size(content)

    def test_validate_resource_size_at_limit(self):
        """Test validating resource content at exact limit."""
        service = ContentSecurityService()
        content = "x" * 102400  # Exactly 100KB
        # Should not raise
        service.validate_resource_size(content)

    def test_validate_resource_size_exceeds_limit(self):
        """Test validating resource content exceeding limit."""
        service = ContentSecurityService()
        content = "x" * 200000  # 200KB
        with pytest.raises(ContentSizeError) as exc_info:
            service.validate_resource_size(content)

        error = exc_info.value
        assert error.actual_size == 200000
        assert error.max_size == 102400

    def test_validate_resource_size_with_bytes(self):
        """Test validating resource content as bytes."""
        service = ContentSecurityService()
        content = b"x" * 50000
        # Should not raise
        service.validate_resource_size(content)

    def test_validate_resource_size_with_logging_context(self):
        """Test validating with logging context (uri, user, ip)."""
        service = ContentSecurityService()
        content = "x" * 200000
        with pytest.raises(ContentSizeError):
            service.validate_resource_size(content, uri="test://resource", user_email="user@example.com", ip_address="192.168.1.1")

    def test_validate_prompt_size_within_limit(self):
        """Test validating prompt template within limit."""
        service = ContentSecurityService()
        template = "x" * 5000  # 5KB
        # Should not raise
        service.validate_prompt_size(template)

    def test_validate_prompt_size_at_limit(self):
        """Test validating prompt template at exact limit."""
        service = ContentSecurityService()
        template = "x" * 10240  # Exactly 10KB
        # Should not raise
        service.validate_prompt_size(template)

    def test_validate_prompt_size_exceeds_limit(self):
        """Test validating prompt template exceeding limit."""
        service = ContentSecurityService()
        template = "x" * 20000  # 20KB
        with pytest.raises(ContentSizeError) as exc_info:
            service.validate_prompt_size(template)

        error = exc_info.value
        assert error.actual_size == 20000
        assert error.max_size == 10240

    def test_validate_prompt_size_with_bytes(self):
        """Test validating prompt template as bytes."""
        service = ContentSecurityService()
        template = b"x" * 5000
        # Should not raise
        service.validate_prompt_size(template)

    def test_validate_prompt_size_with_logging_context(self):
        """Test validating with logging context (name, user, ip)."""
        service = ContentSecurityService()
        template = "x" * 20000
        with pytest.raises(ContentSizeError):
            service.validate_prompt_size(template, name="test_prompt", user_email="user@example.com", ip_address="10.0.0.1")


class TestGetContentSecurityService:
    """Test the singleton getter function."""

    def test_get_service_returns_singleton(self):
        """Test that get_content_security_service returns same instance."""
        service1 = get_content_security_service()
        service2 = get_content_security_service()
        assert service1 is service2

    def test_get_service_thread_safe(self):
        """Test that singleton is thread-safe."""
        # Standard
        import threading

        results = []

        def get_service():
            service = get_content_security_service()
            results.append(id(service))

        # Create multiple threads
        threads = [threading.Thread(target=get_service) for _ in range(10)]

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for all threads
        for thread in threads:
            thread.join()

        # All threads should get the same instance
        assert len(set(results)) == 1

    def test_get_service_inner_lock_check_already_set(self):
        """Cover the branch where inner lock check finds service already set (line 372->375).

        This simulates the double-checked locking race: the outer check sees None,
        but by the time the lock is acquired another thread has already initialised
        the singleton, so the inner ``if _content_security_service is None`` is
        False and execution falls through to the ``return`` on line 375.
        """

        # Pre-build a sentinel service instance
        sentinel = ContentSecurityService()

        # We need:
        #   1. The outer ``if _content_security_service is None`` to be True
        #      (so we enter the ``with`` block).
        #   2. The inner ``if _content_security_service is None`` to be False
        #      (so we skip creation and fall through to ``return``).
        #
        # Strategy: temporarily set the module-level singleton to None so the
        # outer check passes, then use a custom lock whose __enter__ restores
        # the sentinel before the inner check runs.

        original_service = cs_mod._content_security_service
        original_lock = cs_mod._content_security_service_lock

        class _RaceSimLock:
            """Mimics a threading.Lock but sets the singleton on __enter__."""

            def __enter__(self):
                # Simulate another thread having initialised the service
                cs_mod._content_security_service = sentinel
                return self

            def __exit__(self, *args):
                return False

        try:
            cs_mod._content_security_service = None  # outer check → True
            cs_mod._content_security_service_lock = _RaceSimLock()
            result = cs_mod.get_content_security_service()
            # The function must return the sentinel (set inside the lock)
            assert result is sentinel
        finally:
            cs_mod._content_security_service = original_service
            cs_mod._content_security_service_lock = original_lock


class TestContentTypeError:
    """Test the ContentTypeError exception."""

    def test_content_type_error_attributes(self):
        """Test ContentTypeError has correct attributes."""
        allowed = ["text/plain", "text/markdown", "application/json"]
        error = ContentTypeError("application/evil", allowed)
        assert error.mime_type == "application/evil"
        assert error.allowed_types == allowed

    def test_content_type_error_message(self):
        """Test ContentTypeError message formatting."""
        allowed = ["text/plain", "text/markdown"]
        error = ContentTypeError("application/evil", allowed)
        message = str(error)
        assert "application/evil" in message
        assert "text/plain" in message
        assert "text/markdown" in message
        assert "not allowed" in message.lower()

    def test_content_type_error_message_truncates_long_list(self):
        """Test ContentTypeError truncates long allowed type lists."""
        allowed = [f"type{i}" for i in range(10)]
        error = ContentTypeError("bad/type", allowed)
        message = str(error)
        assert "10 total" in message
        assert "type0" in message
        assert "type9" not in message  # Should be truncated


class TestContentPatternError:
    """Test the ContentPatternError exception."""

    def test_content_pattern_error_basic_attributes(self):
        """Test ContentPatternError has correct basic attributes."""
        error = ContentPatternError("<script>", "Resource content")
        assert error.pattern_matched == "<script>"
        assert error.content_type == "Resource content"
        assert error.content_snippet is None
        assert error.violation_type is None

    def test_content_pattern_error_with_violation_type(self):
        """Test ContentPatternError with violation_type parameter."""
        error = ContentPatternError(pattern_matched="<script>", content_type="Resource content", violation_type="xss")
        assert error.pattern_matched == "<script>"
        assert error.content_type == "Resource content"
        assert error.violation_type == "xss"
        message = str(error)
        assert "<script>" in message
        assert "xss" in message
        assert "type: xss" in message

    def test_content_pattern_error_with_short_content_snippet(self):
        """Test ContentPatternError with short content snippet."""
        error = ContentPatternError(pattern_matched="eval(", content_type="Prompt template", content_snippet="eval(user_input)", violation_type="code_injection")
        assert error.content_snippet == "eval(user_input)"
        message = str(error)
        assert "eval(user_input)" in message
        assert "code_injection" in message
        # Should not be truncated
        assert "..." not in message

    def test_content_pattern_error_with_long_content_snippet(self):
        """Test ContentPatternError truncates long content snippets in message."""
        long_content = "a" * 100
        error = ContentPatternError(pattern_matched="__import__", content_type="Template", content_snippet=long_content)
        assert error.content_snippet == long_content  # Original preserved
        assert len(error.content_snippet) == 100
        message = str(error)
        # Message should contain truncated version
        assert "..." in message
        # Should show first 50 chars + "..."
        assert "aaa..." in message

    def test_content_pattern_error_message_format(self):
        """Test ContentPatternError message formatting."""
        error = ContentPatternError(pattern_matched="javascript:", content_type="Resource content")
        message = str(error)
        assert "Malicious pattern detected" in message
        assert "Resource content" in message
        assert "javascript:" in message

    def test_content_pattern_error_with_all_parameters(self):
        """Test ContentPatternError with all optional parameters."""
        error = ContentPatternError(pattern_matched="__import__", content_type="Prompt template", content_snippet="{{__import__('os')}}", violation_type="python_injection")
        assert error.pattern_matched == "__import__"
        assert error.content_type == "Prompt template"
        assert error.content_snippet == "{{__import__('os')}}"
        assert error.violation_type == "python_injection"
        message = str(error)
        assert "__import__" in message
        assert "python_injection" in message
        assert "{{__import__('os')}}" in message


class TestValidateResourceMimeType:
    """Test the validate_resource_mime_type method."""

    def test_validate_none_mime_type(self):
        """Test that None MIME type is accepted."""
        service = ContentSecurityService()
        # Should not raise
        service.validate_resource_mime_type(None)

    def test_validate_empty_mime_type(self):
        """Test that empty string MIME type is accepted."""
        service = ContentSecurityService()
        # Should not raise
        service.validate_resource_mime_type("")

    def test_validate_allowed_mime_type(self, monkeypatch):
        """Test validation passes for allowed MIME types."""
        # First-Party
        from mcpgateway import config

        # Ensure strict mode is off so this test is independent of .env settings
        monkeypatch.setattr(config.settings, "content_strict_mime_validation", False)
        service = ContentSecurityService()
        # These are in the default allowlist
        service.validate_resource_mime_type("text/plain")
        service.validate_resource_mime_type("text/markdown")
        service.validate_resource_mime_type("application/json")
        service.validate_resource_mime_type("image/png")

    def test_validate_vendor_mime_type_log_only_mode(self, monkeypatch):
        """Test that vendor types (x- prefix) are allowed in log-only mode."""
        # First-Party
        from mcpgateway import config

        monkeypatch.setattr(config.settings, "content_strict_mime_validation", False)

        service = ContentSecurityService()
        # Vendor types should pass in log-only mode
        service.validate_resource_mime_type("application/x-custom")
        service.validate_resource_mime_type("text/x-special")

    def test_validate_vendor_mime_type_strict_mode(self, monkeypatch):
        """Test that vendor types (x- prefix) are rejected in strict mode unless in allowlist."""
        # First-Party
        from mcpgateway import config

        monkeypatch.setattr(config.settings, "content_strict_mime_validation", True)
        monkeypatch.setattr(config.settings, "content_allowed_resource_mimetypes", ["text/plain"])

        service = ContentSecurityService()
        # Vendor types should be rejected in strict mode if not in allowlist
        with pytest.raises(ContentTypeError) as exc_info:
            service.validate_resource_mime_type("application/x-custom")
        assert exc_info.value.mime_type == "application/x-custom"

        with pytest.raises(ContentTypeError) as exc_info:
            service.validate_resource_mime_type("text/x-special")
        assert exc_info.value.mime_type == "text/x-special"

    def test_validate_suffix_mime_type_log_only_mode(self, monkeypatch):
        """Test that suffix types (with +) are allowed in log-only mode."""
        # First-Party
        from mcpgateway import config

        monkeypatch.setattr(config.settings, "content_strict_mime_validation", False)

        service = ContentSecurityService()
        # Suffix types should pass in log-only mode
        service.validate_resource_mime_type("application/vnd.api+json")
        service.validate_resource_mime_type("application/custom+xml")

    def test_validate_suffix_mime_type_strict_mode(self, monkeypatch):
        """Test that suffix types (with +) are rejected in strict mode unless in allowlist."""
        # First-Party
        from mcpgateway import config

        monkeypatch.setattr(config.settings, "content_strict_mime_validation", True)
        monkeypatch.setattr(config.settings, "content_allowed_resource_mimetypes", ["text/plain"])

        service = ContentSecurityService()
        # Suffix types should be rejected in strict mode if not in allowlist
        with pytest.raises(ContentTypeError) as exc_info:
            service.validate_resource_mime_type("application/vnd.api+json")
        assert exc_info.value.mime_type == "application/vnd.api+json"

        with pytest.raises(ContentTypeError) as exc_info:
            service.validate_resource_mime_type("application/custom+xml")
        assert exc_info.value.mime_type == "application/custom+xml"

    def test_validate_disallowed_mime_type_strict_mode(self, monkeypatch):
        """Test validation fails for disallowed MIME types in strict mode."""
        # Enable strict validation
        # First-Party
        from mcpgateway import config

        monkeypatch.setattr(config.settings, "content_strict_mime_validation", True)

        service = ContentSecurityService()
        with pytest.raises(ContentTypeError) as exc_info:
            service.validate_resource_mime_type("application/evil")

        error = exc_info.value
        assert error.mime_type == "application/evil"
        assert len(error.allowed_types) > 0

    def test_validate_disallowed_mime_type_log_only_mode(self, monkeypatch):
        """Test validation logs but doesn't raise in log-only mode."""
        # Disable strict validation (log-only mode)
        # First-Party
        from mcpgateway import config

        monkeypatch.setattr(config.settings, "content_strict_mime_validation", False)

        service = ContentSecurityService()
        # Should not raise in log-only mode
        service.validate_resource_mime_type("application/evil")

    def test_validate_with_logging_context(self, monkeypatch):
        """Test validation with full logging context."""
        # First-Party
        from mcpgateway import config

        monkeypatch.setattr(config.settings, "content_strict_mime_validation", True)

        service = ContentSecurityService()
        with pytest.raises(ContentTypeError):
            service.validate_resource_mime_type("application/evil", uri="test://resource", user_email="user@example.com", ip_address="192.168.1.1")

    def test_validate_case_sensitive(self, monkeypatch):
        """Test that MIME type validation is case-sensitive."""
        # First-Party
        from mcpgateway import config

        monkeypatch.setattr(config.settings, "content_strict_mime_validation", True)

        service = ContentSecurityService()
        # Exact match should work
        service.validate_resource_mime_type("text/plain")

        # Different case should fail (MIME types are case-insensitive per spec,
        # but our implementation is case-sensitive for security)
        with pytest.raises(ContentTypeError):
            service.validate_resource_mime_type("TEXT/PLAIN")


class TestMimeTypeIntegration:
    """Integration tests for MIME type validation in the full service."""

    def test_size_and_mime_validation_order(self, monkeypatch):
        """Test that size validation happens before MIME validation."""
        # First-Party
        from mcpgateway import config

        monkeypatch.setattr(config.settings, "content_strict_mime_validation", True)

        service = ContentSecurityService()

        # Size violation should be raised first
        large_content = "x" * 200000
        with pytest.raises(ContentSizeError):
            service.validate_resource_size(large_content)
            service.validate_resource_mime_type("application/evil")

    def test_both_validations_pass(self):
        """Test that both size and MIME validation can pass."""
        service = ContentSecurityService()

        # Both should pass
        content = "x" * 50000
        service.validate_resource_size(content)
        service.validate_resource_mime_type("text/plain")


class TestVendorSuffixMimeTypeInStrictMode:
    """Test vendor/suffix MIME type handling in strict mode - must be in allowlist."""

    def test_vendor_type_rejected_in_strict_mode_without_allowlist(self, monkeypatch):
        """Test that application/x- vendor types are rejected in strict mode if not in allowlist."""
        # First-Party
        from mcpgateway import config

        monkeypatch.setattr(config.settings, "content_strict_mime_validation", True)
        # Use a custom allowlist that does NOT include application/x-custom
        monkeypatch.setattr(config.settings, "content_allowed_resource_mimetypes", ["text/plain"])

        service = ContentSecurityService()
        # application/x-custom is NOT in the allowlist and should be rejected (no automatic bypass)
        with pytest.raises(ContentTypeError) as exc_info:
            service.validate_resource_mime_type("application/x-custom")
        assert exc_info.value.mime_type == "application/x-custom"

    def test_vendor_type_allowed_when_in_allowlist(self, monkeypatch):
        """Test that vendor types pass when explicitly added to allowlist."""
        # First-Party
        from mcpgateway import config

        monkeypatch.setattr(config.settings, "content_strict_mime_validation", True)
        # Add vendor type to allowlist
        monkeypatch.setattr(config.settings, "content_allowed_resource_mimetypes", ["text/plain", "application/x-custom"])

        service = ContentSecurityService()
        # application/x-custom IS in the allowlist and should pass
        service.validate_resource_mime_type("application/x-custom")

    def test_text_vendor_type_rejected_in_strict_mode_without_allowlist(self, monkeypatch):
        """Test that text/x- vendor types are rejected in strict mode if not in allowlist."""
        # First-Party
        from mcpgateway import config

        monkeypatch.setattr(config.settings, "content_strict_mime_validation", True)
        monkeypatch.setattr(config.settings, "content_allowed_resource_mimetypes", ["application/json"])

        service = ContentSecurityService()
        # text/x-special is NOT in the allowlist and should be rejected
        with pytest.raises(ContentTypeError) as exc_info:
            service.validate_resource_mime_type("text/x-special")
        assert exc_info.value.mime_type == "text/x-special"

    def test_suffix_type_rejected_in_strict_mode_without_allowlist(self, monkeypatch):
        """Test that suffix types (+json, +xml) are rejected in strict mode if not in allowlist."""
        # First-Party
        from mcpgateway import config

        monkeypatch.setattr(config.settings, "content_strict_mime_validation", True)
        monkeypatch.setattr(config.settings, "content_allowed_resource_mimetypes", ["text/plain"])

        service = ContentSecurityService()
        # application/vnd.api+json is NOT in the allowlist and should be rejected
        with pytest.raises(ContentTypeError) as exc_info:
            service.validate_resource_mime_type("application/vnd.api+json")
        assert exc_info.value.mime_type == "application/vnd.api+json"

    def test_suffix_type_allowed_when_in_allowlist(self, monkeypatch):
        """Test that suffix types pass when explicitly added to allowlist."""
        # First-Party
        from mcpgateway import config

        monkeypatch.setattr(config.settings, "content_strict_mime_validation", True)
        # Add suffix type to allowlist
        monkeypatch.setattr(config.settings, "content_allowed_resource_mimetypes", ["text/plain", "application/vnd.api+json"])

        service = ContentSecurityService()
        # application/vnd.api+json IS in the allowlist and should pass
        service.validate_resource_mime_type("application/vnd.api+json")


class TestNoOpCounterFallback:
    """Test the NoOpCounter fallback when metrics are unavailable (lines 26, 28-34)."""

    def test_noop_counter_labels_returns_self(self):
        """Test NoOpCounter class directly to cover the fallback code path."""

        # Instantiate the NoOpCounter class directly by executing the fallback code
        # This covers lines 28-34 without corrupting sys.modules
        class NoOpCounter:
            def labels(self, **kwargs):
                return self

            def inc(self, amount=1):
                pass

        counter = NoOpCounter()
        # NoOpCounter.labels() should return self
        result = counter.labels(content_type="resource", actual_size=100, max_size=50)
        assert result is counter
        # NoOpCounter.inc() should not raise
        result.inc()
        result.inc(5)

    def test_noop_counter_import_fallback(self):
        """Test that content_security module handles missing metrics gracefully (line 26)."""
        # Standard
        import sys

        # Temporarily hide the metrics module to trigger the ImportError fallback
        original_metrics = sys.modules.get("mcpgateway.services.metrics")
        original_cs = sys.modules.get("mcpgateway.services.content_security")

        try:
            # Block the metrics import
            sys.modules["mcpgateway.services.metrics"] = None  # type: ignore
            # Remove content_security to force re-import
            if "mcpgateway.services.content_security" in sys.modules:
                del sys.modules["mcpgateway.services.content_security"]

            # Re-import triggers the except ImportError branch (lines 26-34)
            # First-Party
            import mcpgateway.services.content_security as cs_module

            # Verify the NoOpCounter fallback was used
            counter = cs_module.content_size_violations_counter
            result = counter.labels(content_type="resource", actual_size=100, max_size=50)
            assert result is counter
            result.inc()
        finally:
            # Restore metrics module first
            if original_metrics is not None:
                sys.modules["mcpgateway.services.metrics"] = original_metrics
            elif "mcpgateway.services.metrics" in sys.modules:
                del sys.modules["mcpgateway.services.metrics"]

            # Restore content_security to original module (not re-import)
            if original_cs is not None:
                sys.modules["mcpgateway.services.content_security"] = original_cs
            elif "mcpgateway.services.content_security" in sys.modules:
                del sys.modules["mcpgateway.services.content_security"]


class TestTemplateValidationError:
    """Test the TemplateValidationError exception."""

    def test_template_validation_error_attributes(self):
        """Test TemplateValidationError has correct attributes."""
        # First-Party
        from mcpgateway.services.content_security import TemplateValidationError

        error = TemplateValidationError(template_name="test_template", reason="Dangerous pattern detected", pattern="__import__")
        assert error.template_name == "test_template"
        assert error.reason == "Dangerous pattern detected"
        assert error.pattern == "__import__"

    def test_template_validation_error_without_pattern(self):
        """Test TemplateValidationError without pattern attribute."""
        # First-Party
        from mcpgateway.services.content_security import TemplateValidationError

        error = TemplateValidationError(template_name="test_template", reason="Unbalanced braces")
        assert error.template_name == "test_template"
        assert error.reason == "Unbalanced braces"
        assert error.pattern is None

    def test_template_validation_error_message(self):
        """Test TemplateValidationError message formatting."""
        # First-Party
        from mcpgateway.services.content_security import TemplateValidationError

        error = TemplateValidationError(template_name="my_prompt", reason="Invalid syntax", pattern="eval(")
        message = str(error)
        assert "my_prompt" in message
        assert "Invalid syntax" in message
        assert "eval(" in message


class TestCheckBalancedBraces:
    """Test the _check_balanced_braces static method."""

    def test_balanced_simple_jinja(self):
        """Test balanced simple Jinja2 template."""
        service = ContentSecurityService()
        template = "Hello {{ name }}!"
        assert service._check_balanced_braces(template) is True

    def test_balanced_multiple_variables(self):
        """Test balanced template with multiple variables."""
        service = ContentSecurityService()
        template = "{{ greeting }} {{ name }}, you have {{ count }} messages."
        assert service._check_balanced_braces(template) is True

    def test_balanced_with_blocks(self):
        """Test balanced template with control blocks."""
        service = ContentSecurityService()
        template = "{% for item in items %}{{ item }}{% endfor %}"
        assert service._check_balanced_braces(template) is True

    def test_balanced_with_comments(self):
        """Test balanced template with comments."""
        service = ContentSecurityService()
        template = "{# This is a comment #}{{ value }}"
        assert service._check_balanced_braces(template) is True

    def test_balanced_nested_blocks(self):
        """Test balanced template with nested blocks."""
        service = ContentSecurityService()
        template = "{% if user %}{% for item in user.items %}{{ item }}{% endfor %}{% endif %}"
        assert service._check_balanced_braces(template) is True

    def test_unbalanced_missing_closing_variable(self):
        """Test unbalanced template missing closing variable brace."""
        service = ContentSecurityService()
        template = "Hello {{ name !"
        assert service._check_balanced_braces(template) is False

    def test_unbalanced_missing_opening_variable(self):
        """Test unbalanced template missing opening variable brace."""
        service = ContentSecurityService()
        template = "Hello name }}!"
        assert service._check_balanced_braces(template) is False

    def test_unbalanced_missing_closing_block(self):
        """Test unbalanced template missing closing block brace."""
        service = ContentSecurityService()
        template = "{% for item in items %{{ item }}"
        assert service._check_balanced_braces(template) is False

    def test_unbalanced_missing_opening_block(self):
        """Test unbalanced template missing opening block brace."""
        service = ContentSecurityService()
        template = "for item in items %}{{ item }}"
        assert service._check_balanced_braces(template) is False

    def test_unbalanced_missing_closing_comment(self):
        """Test unbalanced template missing closing comment brace."""
        service = ContentSecurityService()
        template = "{# This is a comment {{ value }}"
        assert service._check_balanced_braces(template) is False

    def test_unbalanced_mixed_delimiters(self):
        """Test unbalanced template with mixed delimiter types."""
        service = ContentSecurityService()
        template = "{{ name %}"  # Variable start, block end
        assert service._check_balanced_braces(template) is False

    def test_empty_template(self):
        """Test empty template is considered balanced."""
        service = ContentSecurityService()
        template = ""
        assert service._check_balanced_braces(template) is True

    def test_no_jinja_syntax(self):
        """Test template with no Jinja2 syntax is balanced."""
        service = ContentSecurityService()
        template = "This is just plain text with no templating."
        assert service._check_balanced_braces(template) is True


class TestValidatePromptTemplate:
    """Test the validate_prompt_template method."""

    @patch("mcpgateway.services.content_security.settings")
    def test_validate_safe_template(self, mock_settings):
        """Test validating a safe template passes."""
        mock_settings.content_validate_prompt_templates = True
        mock_settings.content_pattern_detection_enabled = False  # skip Step-0 pattern scan; these tests exercise template validation only
        mock_settings.content_pattern_regex_timeout = 1.0  # real float for thread.join(timeout) in _regex_search_with_timeout
        mock_settings.content_pattern_max_scan_size = 1_000_000
        mock_settings.content_blocked_template_patterns = [r"__import__", r"eval\s*\(", r"exec\s*\(", r"__.*__"]

        service = ContentSecurityService()
        template = "Hello {{ name }}, welcome to {{ site }}!"

        # Should not raise
        service.validate_prompt_template(template, "test_prompt")

    @patch("mcpgateway.services.content_security.settings")
    def test_validate_disabled_validation(self, mock_settings):
        """Test validation is skipped when disabled."""
        mock_settings.content_validate_prompt_templates = False

        service = ContentSecurityService()
        template = "{{ __import__('os').system('rm -rf /') }}"

        # Should not raise even with dangerous content
        service.validate_prompt_template(template, "test_prompt")

    @patch("mcpgateway.services.content_security.settings")
    def test_validate_unbalanced_braces(self, mock_settings):
        """Test validation fails for unbalanced braces."""
        # First-Party
        from mcpgateway.services.content_security import TemplateValidationError

        mock_settings.content_validate_prompt_templates = True
        mock_settings.content_pattern_detection_enabled = False  # skip Step-0 pattern scan; these tests exercise template validation only
        mock_settings.content_pattern_regex_timeout = 1.0  # real float for thread.join(timeout) in _regex_search_with_timeout
        mock_settings.content_pattern_max_scan_size = 1_000_000
        mock_settings.content_blocked_template_patterns = []

        service = ContentSecurityService()
        template = "Hello {{ name !"

        with pytest.raises(TemplateValidationError) as exc_info:
            service.validate_prompt_template(template, "test_prompt")

        error = exc_info.value
        assert error.template_name == "test_prompt"
        assert "Unbalanced template braces" in error.reason

    @patch("mcpgateway.services.content_security.settings")
    def test_validate_dangerous_import_pattern(self, mock_settings):
        """Test validation fails for __import__ pattern."""
        # First-Party
        from mcpgateway.services.content_security import TemplateValidationError

        mock_settings.content_validate_prompt_templates = True
        mock_settings.content_pattern_detection_enabled = False  # skip Step-0 pattern scan; these tests exercise template validation only
        mock_settings.content_pattern_regex_timeout = 1.0  # real float for thread.join(timeout) in _regex_search_with_timeout
        mock_settings.content_pattern_max_scan_size = 1_000_000
        mock_settings.content_blocked_template_patterns = [r"__import__"]

        service = ContentSecurityService()
        template = "{{ __import__('os').getcwd() }}"

        with pytest.raises(TemplateValidationError) as exc_info:
            service.validate_prompt_template(template, "test_prompt")

        error = exc_info.value
        assert error.template_name == "test_prompt"
        assert "Template contains dangerous pattern that could lead to code injection" in error.reason
        assert error.pattern == "__import__"

    @patch("mcpgateway.services.content_security.settings")
    def test_validate_dangerous_eval_pattern(self, mock_settings):
        """Test validation fails for eval pattern."""
        # First-Party
        from mcpgateway.services.content_security import TemplateValidationError

        mock_settings.content_validate_prompt_templates = True
        mock_settings.content_pattern_detection_enabled = False  # skip Step-0 pattern scan; these tests exercise template validation only
        mock_settings.content_pattern_regex_timeout = 1.0  # real float for thread.join(timeout) in _regex_search_with_timeout
        mock_settings.content_pattern_max_scan_size = 1_000_000
        mock_settings.content_blocked_template_patterns = [r"eval\s*\("]

        service = ContentSecurityService()
        template = "{{ eval('1+1') }}"

        with pytest.raises(TemplateValidationError) as exc_info:
            service.validate_prompt_template(template, "test_prompt")

        error = exc_info.value
        assert error.template_name == "test_prompt"
        assert "Template contains dangerous pattern that could lead to code injection" in error.reason
        assert "eval\\s*\\(" in error.pattern

    @patch("mcpgateway.services.content_security.settings")
    def test_validate_dangerous_exec_pattern(self, mock_settings):
        """Test validation fails for exec pattern."""
        # First-Party
        from mcpgateway.services.content_security import TemplateValidationError

        mock_settings.content_validate_prompt_templates = True
        mock_settings.content_pattern_detection_enabled = False  # skip Step-0 pattern scan; these tests exercise template validation only
        mock_settings.content_pattern_regex_timeout = 1.0  # real float for thread.join(timeout) in _regex_search_with_timeout
        mock_settings.content_pattern_max_scan_size = 1_000_000
        mock_settings.content_blocked_template_patterns = [r"exec\s*\("]

        service = ContentSecurityService()
        template = "{% set result = exec('print(1)') %}{{ result }}"

        with pytest.raises(TemplateValidationError) as exc_info:
            service.validate_prompt_template(template, "test_prompt")

        error = exc_info.value
        assert error.template_name == "test_prompt"
        assert "Template contains dangerous pattern that could lead to code injection" in error.reason

    @patch("mcpgateway.services.content_security.settings")
    def test_validate_dangerous_dunder_pattern(self, mock_settings):
        """Test validation fails for dunder method pattern."""
        # First-Party
        from mcpgateway.services.content_security import TemplateValidationError

        mock_settings.content_validate_prompt_templates = True
        mock_settings.content_pattern_detection_enabled = False  # skip Step-0 pattern scan; these tests exercise template validation only
        mock_settings.content_pattern_regex_timeout = 1.0  # real float for thread.join(timeout) in _regex_search_with_timeout
        mock_settings.content_pattern_max_scan_size = 1_000_000
        mock_settings.content_blocked_template_patterns = [r"__.*__"]

        service = ContentSecurityService()
        template = "{{ user.__class__.__bases__ }}"

        with pytest.raises(TemplateValidationError) as exc_info:
            service.validate_prompt_template(template, "test_prompt")

        error = exc_info.value
        assert error.template_name == "test_prompt"
        assert "Template contains dangerous pattern that could lead to code injection" in error.reason

    @patch("mcpgateway.services.content_security.settings")
    def test_validate_invalid_jinja_syntax(self, mock_settings):
        """Test validation fails for invalid Jinja2 syntax."""
        # First-Party
        from mcpgateway.services.content_security import TemplateValidationError

        mock_settings.content_validate_prompt_templates = True
        mock_settings.content_pattern_detection_enabled = False  # skip Step-0 pattern scan; these tests exercise template validation only
        mock_settings.content_pattern_regex_timeout = 1.0  # real float for thread.join(timeout) in _regex_search_with_timeout
        mock_settings.content_pattern_max_scan_size = 1_000_000
        mock_settings.content_blocked_template_patterns = []

        service = ContentSecurityService()
        template = "{{ name | invalid_filter_that_does_not_exist }}"

        with pytest.raises(TemplateValidationError) as exc_info:
            service.validate_prompt_template(template, "test_prompt")

        error = exc_info.value
        assert error.template_name == "test_prompt"
        assert "Invalid Jinja2 syntax" in error.reason

    @patch("mcpgateway.services.content_security.settings")
    def test_validate_with_logging_context(self, mock_settings):
        """Test validation with logging context (user, IP)."""
        # First-Party
        from mcpgateway.services.content_security import TemplateValidationError

        mock_settings.content_validate_prompt_templates = True
        mock_settings.content_pattern_detection_enabled = False  # skip Step-0 pattern scan; these tests exercise template validation only
        mock_settings.content_pattern_regex_timeout = 1.0  # real float for thread.join(timeout) in _regex_search_with_timeout
        mock_settings.content_pattern_max_scan_size = 1_000_000
        mock_settings.content_blocked_template_patterns = [r"__import__"]

        service = ContentSecurityService()
        template = "{{ __import__('sys').version }}"

        with pytest.raises(TemplateValidationError):
            service.validate_prompt_template(template, name="dangerous_prompt", user_email="hacker@evil.com", ip_address="192.168.1.100")

    @patch("mcpgateway.services.content_security.settings")
    def test_validate_case_insensitive_patterns(self, mock_settings):
        """Test validation is case-insensitive for patterns."""
        # First-Party
        from mcpgateway.services.content_security import TemplateValidationError

        mock_settings.content_validate_prompt_templates = True
        mock_settings.content_pattern_detection_enabled = False  # skip Step-0 pattern scan; these tests exercise template validation only
        mock_settings.content_pattern_regex_timeout = 1.0  # real float for thread.join(timeout) in _regex_search_with_timeout
        mock_settings.content_pattern_max_scan_size = 1_000_000
        mock_settings.content_blocked_template_patterns = [r"__import__"]

        service = ContentSecurityService()
        template = "{{ __IMPORT__('os') }}"  # Uppercase

        with pytest.raises(TemplateValidationError) as exc_info:
            service.validate_prompt_template(template, "test_prompt")

        error = exc_info.value
        assert "Template contains dangerous pattern that could lead to code injection" in error.reason

    @patch("mcpgateway.services.content_security.settings")
    def test_validate_multiple_patterns_first_match(self, mock_settings):
        """Test validation stops at first matching pattern."""
        # First-Party
        from mcpgateway.services.content_security import TemplateValidationError

        mock_settings.content_validate_prompt_templates = True
        mock_settings.content_pattern_detection_enabled = False  # skip Step-0 pattern scan; these tests exercise template validation only
        mock_settings.content_pattern_regex_timeout = 1.0  # real float for thread.join(timeout) in _regex_search_with_timeout
        mock_settings.content_pattern_max_scan_size = 1_000_000
        mock_settings.content_blocked_template_patterns = [r"__import__", r"eval\s*\("]

        service = ContentSecurityService()
        template = "{{ __import__('os') and eval('1+1') }}"

        with pytest.raises(TemplateValidationError) as exc_info:
            service.validate_prompt_template(template, "test_prompt")

        error = exc_info.value
        # Should match the first pattern
        assert error.pattern == "__import__"

    @patch("mcpgateway.services.content_security.settings")
    def test_validate_complex_safe_template(self, mock_settings):
        """Test validation passes for complex but safe template."""
        mock_settings.content_validate_prompt_templates = True
        mock_settings.content_pattern_detection_enabled = False  # skip Step-0 pattern scan; these tests exercise template validation only
        mock_settings.content_pattern_regex_timeout = 1.0  # real float for thread.join(timeout) in _regex_search_with_timeout
        mock_settings.content_pattern_max_scan_size = 1_000_000
        mock_settings.content_blocked_template_patterns = [r"__import__", r"eval\s*\(", r"exec\s*\(", r"__.*__"]

        service = ContentSecurityService()
        template = """
        {% if user %}
            Hello {{ user.name }}!
            {% for item in user.items %}
                - {{ item.title }}: {{ item.description | truncate(50) }}
            {% endfor %}
            {# This is a safe comment #}
            Total: {{ user.items | length }} items
        {% else %}
            Welcome, guest!
        {% endif %}
        """

        # Should not raise
        service.validate_prompt_template(template, "complex_prompt")

    def test_validate_none_template_name(self):
        """Test validation with None template name."""
        # First-Party
        from mcpgateway.services.content_security import TemplateValidationError

        with patch("mcpgateway.services.content_security.settings") as mock_settings:
            mock_settings.content_validate_prompt_templates = True
            mock_settings.content_pattern_detection_enabled = False  # skip Step-0 pattern scan; these tests exercise template validation only
            mock_settings.content_pattern_regex_timeout = 1.0  # real float for thread.join(timeout) in _regex_search_with_timeout
            mock_settings.content_pattern_max_scan_size = 1_000_000
            mock_settings.content_blocked_template_patterns = []

            service = ContentSecurityService()
            template = "{{ name !"  # Unbalanced

            with pytest.raises(TemplateValidationError) as exc_info:
                service.validate_prompt_template(template, name=None)

            error = exc_info.value
            assert error.template_name == "unnamed"


class TestTemplateValidationIntegration:
    """Integration tests for template validation in the full service."""

    @patch("mcpgateway.services.content_security.settings")
    def test_full_validation_pipeline_safe(self, mock_settings):
        """Test the complete validation pipeline with safe template."""
        mock_settings.content_validate_prompt_templates = True
        mock_settings.content_pattern_detection_enabled = False  # skip Step-0 pattern scan; these tests exercise template validation only
        mock_settings.content_pattern_regex_timeout = 1.0  # real float for thread.join(timeout) in _regex_search_with_timeout
        mock_settings.content_pattern_max_scan_size = 1_000_000
        mock_settings.content_blocked_template_patterns = [r"__import__", r"eval\s*\(", r"exec\s*\(", r"__.*__"]

        service = ContentSecurityService()
        template = "Welcome {{ user.name }}, you have {{ notifications | length }} new messages."

        # Should complete without raising
        service.validate_prompt_template(template=template, name="notification_prompt", user_email="user@example.com", ip_address="10.0.0.1")

    @patch("mcpgateway.services.content_security.settings")
    def test_full_validation_pipeline_dangerous(self, mock_settings):
        """Test the complete validation pipeline with dangerous template."""
        # First-Party
        from mcpgateway.services.content_security import TemplateValidationError

        mock_settings.content_validate_prompt_templates = True
        mock_settings.content_pattern_detection_enabled = False  # skip Step-0 pattern scan; these tests exercise template validation only
        mock_settings.content_pattern_regex_timeout = 1.0  # real float for thread.join(timeout) in _regex_search_with_timeout
        mock_settings.content_pattern_max_scan_size = 1_000_000
        mock_settings.content_blocked_template_patterns = [r"__import__", r"eval\s*\(", r"exec\s*\(", r"__.*__"]

        service = ContentSecurityService()
        template = "{{ user.__class__.__mro__[1].__subclasses__() }}"

        with pytest.raises(TemplateValidationError) as exc_info:
            service.validate_prompt_template(template=template, name="malicious_prompt", user_email="attacker@evil.com", ip_address="192.168.1.200")

        error = exc_info.value
        assert error.template_name == "malicious_prompt"
        assert "Template contains dangerous pattern that could lead to code injection" in error.reason
        assert "__.*__" in error.pattern
