"""Tests for UAID domain allowlist validation at registration and invocation.

These tests verify the fail-closed security behavior that prevents SSRF
via locally-registered agents with UAID-enabled external endpoints.
"""

import pytest

from mcpgateway.services.a2a_service import _validate_uaid_endpoint_domain


class TestUAIDDomainAllowlistValidation:
    """Test the core domain allowlist validation function."""

    def test_validation_blocked_when_allowlist_empty(self, monkeypatch):
        """Verify validation blocks when allowlist empty (fail-closed)."""
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", [])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        with pytest.raises(ValueError, match="UAID_ALLOWED_DOMAINS is empty"):
            _validate_uaid_endpoint_domain("http://external.example.com/api", "test")

    def test_validation_blocked_when_domain_not_in_allowlist(self, monkeypatch):
        """Verify validation blocks when domain not in allowlist."""
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["trusted.com", "allowed.com"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        with pytest.raises(ValueError, match="not in UAID_ALLOWED_DOMAINS"):
            _validate_uaid_endpoint_domain("http://external.example.com/api", "test")

    def test_validation_allowed_when_domain_in_allowlist(self, monkeypatch):
        """Verify validation succeeds when domain in allowlist."""
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        # Should not raise
        _validate_uaid_endpoint_domain("http://external.example.com/api", "test")

    def test_validation_allowed_with_subdomain_in_allowlist(self, monkeypatch):
        """Verify validation succeeds with subdomain matching."""
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        # Should not raise (subdomain of example.com)
        _validate_uaid_endpoint_domain("http://api.example.com/v1/agent", "test")
        _validate_uaid_endpoint_domain("http://agent.api.example.com/v1/agent", "test")

    def test_validation_bypassed_when_bypass_enabled(self, monkeypatch):
        """Verify validation bypassed when bypass flag enabled (dev mode)."""
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", [])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", True)

        # Should not raise (bypass enabled)
        _validate_uaid_endpoint_domain("http://external.example.com/api", "test")

    def test_validation_error_messages_include_context(self, monkeypatch):
        """Verify error messages include operation context."""
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", [])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        with pytest.raises(ValueError) as exc_info:
            _validate_uaid_endpoint_domain("http://external.example.com/api", "registration")

        assert "registration" in str(exc_info.value)
        assert "external.example.com" in str(exc_info.value)
