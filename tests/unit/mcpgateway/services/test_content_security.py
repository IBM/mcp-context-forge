# -*- coding: utf-8 -*-
"""Unit tests for content security service."""

import pytest

from mcpgateway.services.content_security import (
    ContentSecurityService,
    ContentSizeError,
    _format_bytes,
    _sanitize_pii_for_logging,
    get_content_security_service,
    reset_content_security_service,
)


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

    def test_reset_creates_new_instance(self):
        """Test that reset_content_security_service allows a new instance."""
        service1 = get_content_security_service()
        reset_content_security_service()
        service2 = get_content_security_service()
        assert service1 is not service2
