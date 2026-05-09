"""
Unit tests for domain validation edge cases to achieve full coverage.

Covers missing lines:
- Fallback parsing paths (parsed.hostname, IPv6 brackets, regular parsing)
- Malformed IPv6 handling
- Subdomain matching with ports
- Domain with colon but non-numeric port
- Validation error raising
"""

import pytest
from mcpgateway.services.a2a_service import _validate_uaid_endpoint_domain


class TestDomainValidationCoverage:
    """Tests for domain validation edge cases."""

    def test_fallback_hostname_parsing(self, monkeypatch):
        """Test fallback to parsed.hostname when netloc is empty."""
        # This edge case is rare but can happen with malformed URLs
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        # Test with a URL that has hostname but no netloc (edge case)
        # We'll test the validation with a simple hostname
        _validate_uaid_endpoint_domain("example.com", operation_context="test")

    def test_ipv6_with_brackets_no_port(self, monkeypatch):
        """Test IPv6 address with brackets but no port: [::1]."""
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["::1"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        # Should extract ::1 from [::1]
        _validate_uaid_endpoint_domain("[::1]", operation_context="test")

    def test_malformed_ipv6_with_leading_bracket(self, monkeypatch):
        """Test malformed IPv6 with leading bracket - should fail validation gracefully."""
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        # Malformed IPv6 should raise validation error
        with pytest.raises(ValueError, match="Invalid IPv6 URL"):
            _validate_uaid_endpoint_domain("[malformed", operation_context="test")

    def test_domain_with_colon_but_non_numeric_port(self, monkeypatch):
        """Test domain with colon but non-numeric port: example.com:abc."""
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com:abc"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        # Should treat whole thing as hostname since "abc" is not a port
        _validate_uaid_endpoint_domain("example.com:abc", operation_context="test")

    def test_subdomain_match_with_same_port(self, monkeypatch):
        """Test subdomain matching when both have the same port."""
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com:8080"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        # api.example.com:8080 should match example.com:8080
        _validate_uaid_endpoint_domain("https://api.example.com:8080/path", operation_context="test")

    def test_subdomain_match_with_different_ports_fails(self, monkeypatch):
        """Test subdomain matching fails when ports differ."""
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com:8080"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        # api.example.com:9090 should NOT match example.com:8080 (different ports)
        with pytest.raises(ValueError, match="not in UAID_ALLOWED_DOMAINS"):
            _validate_uaid_endpoint_domain("https://api.example.com:9090/path", operation_context="test")

    def test_endpoint_without_port_allowed_with_port_fails(self, monkeypatch):
        """Test endpoint without port fails when allowlist requires port."""
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com:8080"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        # example.com (no port) should NOT match example.com:8080 (requires port)
        with pytest.raises(ValueError, match="not in UAID_ALLOWED_DOMAINS"):
            _validate_uaid_endpoint_domain("https://example.com/path", operation_context="test")

    def test_validation_error_message_includes_details(self, monkeypatch):
        """Test that validation error includes endpoint, allowed domains, and guidance."""
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["allowed.com"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        # Should raise with detailed error message
        with pytest.raises(ValueError) as exc_info:
            _validate_uaid_endpoint_domain("https://blocked.com/path", operation_context="testing validation")

        error_msg = str(exc_info.value)
        assert "testing validation" in error_msg
        assert "blocked.com" in error_msg
        assert "['allowed.com']" in error_msg
        assert "UAID_ALLOWED_DOMAINS" in error_msg

    def test_ipv6_compressed_form(self, monkeypatch):
        """Test IPv6 compressed form without brackets (multiple colons)."""
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["2001:db8::1"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        # Should recognize as IPv6 (multiple colons)
        _validate_uaid_endpoint_domain("2001:db8::1", operation_context="test")

    def test_exact_match_with_port(self, monkeypatch):
        """Test exact match when both endpoint and allowlist have same host and port."""
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com:8080"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        # Exact match should pass
        _validate_uaid_endpoint_domain("https://example.com:8080/path", operation_context="test")

    def test_fallback_to_split_parsing(self, monkeypatch):
        """Test fallback parsing when URL doesn't have protocol."""
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["simple-host"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        # Should handle simple hostname
        _validate_uaid_endpoint_domain("simple-host", operation_context="test")

    def test_ipv6_with_path_extraction(self, monkeypatch):
        """Test IPv6 with path where we need the bracket extraction path."""
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["::1"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        # Test bracket extraction with path
        _validate_uaid_endpoint_domain("[::1]:8080/path", operation_context="test")

    def test_colon_in_domain_but_not_port(self, monkeypatch):
        """Test domain with colon but non-digit after colon."""
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com:notaport"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        # Should treat whole string as domain
        _validate_uaid_endpoint_domain("example.com:notaport", operation_context="test")

    def test_malformed_ipv6_missing_closing_bracket(self, monkeypatch):
        """Test IPv6 with opening bracket but no closing bracket/colon."""
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["[test"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        # Malformed - should raise ValueError from urlparse
        with pytest.raises(ValueError, match="Invalid IPv6 URL"):
            _validate_uaid_endpoint_domain("[test", operation_context="test")
