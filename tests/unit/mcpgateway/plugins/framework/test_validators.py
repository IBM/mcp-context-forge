# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/plugins/framework/test_validators.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Fred Araujo

Tests for the framework's self-contained SecurityValidator.
"""

# Standard
from unittest.mock import patch

# Third-Party
import pytest

# First-Party
from mcpgateway.plugins.framework.validators import SecurityValidator


class TestSecurityValidatorUrl:
    """Tests for SecurityValidator.validate_url."""

    def test_valid_https_url(self):
        result = SecurityValidator.validate_url("https://example.com")
        assert result == "https://example.com"

    def test_valid_http_url(self):
        result = SecurityValidator.validate_url("http://example.com:8080/mcp")
        assert result == "http://example.com:8080/mcp"

    def test_valid_ws_url(self):
        result = SecurityValidator.validate_url("ws://example.com:9000")
        assert result == "ws://example.com:9000"

    def test_valid_wss_url(self):
        result = SecurityValidator.validate_url("wss://secure.example.com/ws")
        assert result == "wss://secure.example.com/ws"

    def test_empty_url_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            SecurityValidator.validate_url("")

    def test_empty_url_with_field_name(self):
        with pytest.raises(ValueError, match="Server URL cannot be empty"):
            SecurityValidator.validate_url("", field_name="Server URL")

    def test_url_exceeds_max_length(self):
        long_url = "https://example.com/" + "a" * 2048
        with pytest.raises(ValueError, match="exceeds maximum length"):
            SecurityValidator.validate_url(long_url)

    def test_disallowed_scheme_ftp(self):
        with pytest.raises(ValueError, match="must start with one of"):
            SecurityValidator.validate_url("ftp://example.com")

    def test_disallowed_scheme_file(self):
        with pytest.raises(ValueError, match="must start with one of"):
            SecurityValidator.validate_url("file:///etc/passwd")

    def test_url_with_newline(self):
        with pytest.raises(ValueError, match="contains line breaks"):
            SecurityValidator.validate_url("https://example.com\n/malicious")

    def test_url_with_carriage_return(self):
        with pytest.raises(ValueError, match="contains line breaks"):
            SecurityValidator.validate_url("https://example.com\r/malicious")

    def test_url_missing_netloc(self):
        with pytest.raises(ValueError, match="is not a valid URL"):
            SecurityValidator.validate_url("http://")

    def test_urlparse_generic_exception(self):
        with patch("mcpgateway.plugins.framework.validators.urlparse", side_effect=RuntimeError("parse failure")):
            with pytest.raises(ValueError, match="is not a valid URL"):
                SecurityValidator.validate_url("https://example.com")

    def test_case_insensitive_scheme(self):
        result = SecurityValidator.validate_url("HTTPS://EXAMPLE.COM")
        assert result == "HTTPS://EXAMPLE.COM"

    # --- Always-enforced hardening checks ---

    def test_credentials_in_url_rejected(self):
        with pytest.raises(ValueError, match="contains credentials"):
            SecurityValidator.validate_url("https://user:pass@example.com/")

    def test_username_only_in_url_rejected(self):
        with pytest.raises(ValueError, match="contains credentials"):
            SecurityValidator.validate_url("https://user@example.com/")

    def test_ipv6_url_rejected(self):
        with pytest.raises(ValueError, match="IPv6"):
            SecurityValidator.validate_url("https://[::1]:8080/")

    def test_ipv6_full_address_rejected(self):
        with pytest.raises(ValueError, match="IPv6"):
            SecurityValidator.validate_url("https://[2001:db8::1]/")

    def test_dangerous_protocol_javascript(self):
        with pytest.raises(ValueError, match="dangerous protocol"):
            SecurityValidator.validate_url("https://example.com?r=javascript:alert(1)")

    def test_dangerous_protocol_data(self):
        with pytest.raises(ValueError, match="dangerous protocol"):
            SecurityValidator.validate_url("https://example.com?r=data:text/html,<h1>hi</h1>")

    def test_zero_address_always_blocked(self):
        """0.0.0.0 is always blocked regardless of ssrf_protection_enabled."""
        with pytest.raises(ValueError, match="invalid IP address"):
            SecurityValidator.validate_url("https://0.0.0.0/")

    def test_spaces_in_domain_rejected(self):
        with pytest.raises(ValueError, match="contains spaces"):
            SecurityValidator.validate_url("https://exam ple.com")

    def test_spaces_in_query_allowed(self):
        result = SecurityValidator.validate_url("https://example.com/path?query=hello world")
        assert result == "https://example.com/path?query=hello world"

    def test_invalid_port_zero(self):
        with pytest.raises(ValueError, match="invalid port"):
            SecurityValidator.validate_url("https://example.com:0/")

    def test_public_hostname_allowed(self):
        result = SecurityValidator.validate_url("https://my-plugin-server.example.com:9000/sse")
        assert result == "https://my-plugin-server.example.com:9000/sse"


class TestSecurityValidatorSsrf:
    """Tests for configurable SSRF IP-range blocking."""

    def test_loopback_blocked_when_ssrf_enabled(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_SSRF_PROTECTION_ENABLED", "true")
        from mcpgateway.plugins.framework.settings import settings

        settings.cache_clear()
        try:
            with pytest.raises(ValueError, match="blocked by SSRF"):
                SecurityValidator.validate_url("https://127.0.0.1/")
        finally:
            settings.cache_clear()

    def test_link_local_blocked_when_ssrf_enabled(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_SSRF_PROTECTION_ENABLED", "true")
        from mcpgateway.plugins.framework.settings import settings

        settings.cache_clear()
        try:
            with pytest.raises(ValueError, match="blocked by SSRF"):
                SecurityValidator.validate_url("https://169.254.169.254/")
        finally:
            settings.cache_clear()

    def test_private_10_blocked_when_ssrf_enabled(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_SSRF_PROTECTION_ENABLED", "true")
        from mcpgateway.plugins.framework.settings import settings

        settings.cache_clear()
        try:
            with pytest.raises(ValueError, match="blocked by SSRF"):
                SecurityValidator.validate_url("https://10.0.0.1/")
        finally:
            settings.cache_clear()

    def test_private_172_blocked_when_ssrf_enabled(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_SSRF_PROTECTION_ENABLED", "true")
        from mcpgateway.plugins.framework.settings import settings

        settings.cache_clear()
        try:
            with pytest.raises(ValueError, match="blocked by SSRF"):
                SecurityValidator.validate_url("https://172.16.0.1/")
        finally:
            settings.cache_clear()

    def test_private_192_blocked_when_ssrf_enabled(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_SSRF_PROTECTION_ENABLED", "true")
        from mcpgateway.plugins.framework.settings import settings

        settings.cache_clear()
        try:
            with pytest.raises(ValueError, match="blocked by SSRF"):
                SecurityValidator.validate_url("https://192.168.1.1/")
        finally:
            settings.cache_clear()

    def test_loopback_allowed_when_ssrf_disabled(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_SSRF_PROTECTION_ENABLED", "false")
        from mcpgateway.plugins.framework.settings import settings

        settings.cache_clear()
        try:
            result = SecurityValidator.validate_url("https://127.0.0.1:8080/mcp")
            assert result == "https://127.0.0.1:8080/mcp"
        finally:
            settings.cache_clear()

    def test_private_ip_allowed_when_ssrf_disabled(self, monkeypatch):
        monkeypatch.setenv("PLUGINS_SSRF_PROTECTION_ENABLED", "false")
        from mcpgateway.plugins.framework.settings import settings

        settings.cache_clear()
        try:
            result = SecurityValidator.validate_url("https://192.168.1.100:9000/sse")
            assert result == "https://192.168.1.100:9000/sse"
        finally:
            settings.cache_clear()


class TestSecurityValidatorSettingsIsolation:
    """URL validation must not fail due to unrelated plugin env var errors."""

    def test_url_validation_succeeds_with_malformed_unrelated_env(self, monkeypatch):
        """A malformed PLUGINS_SERVER_PORT should not break URL validation."""
        from mcpgateway.plugins.framework.settings import settings

        monkeypatch.setenv("PLUGINS_SERVER_PORT", "not_a_number")
        settings.cache_clear()
        try:
            result = SecurityValidator.validate_url("https://example.com/api")
            assert result == "https://example.com/api"
        finally:
            settings.cache_clear()

    def test_ssrf_check_works_with_malformed_unrelated_env(self, monkeypatch):
        """SSRF blocking should work even when unrelated env vars are malformed."""
        from mcpgateway.plugins.framework.settings import settings

        monkeypatch.setenv("PLUGINS_SERVER_PORT", "not_a_number")
        monkeypatch.setenv("PLUGINS_SSRF_PROTECTION_ENABLED", "true")
        settings.cache_clear()
        try:
            with pytest.raises(ValueError, match="blocked by SSRF"):
                SecurityValidator.validate_url("https://10.0.0.1/")
        finally:
            settings.cache_clear()


class TestSecurityValidatorParity:
    """Ensure framework validators stay in sync with gateway validators."""

    def test_security_validator_url_scheme_parity(self):
        """Framework allowed URL schemes must match the gateway's SecurityValidator."""
        from mcpgateway.common.validators import SecurityValidator as GatewayValidator
        from mcpgateway.plugins.framework.validators import _ALLOWED_URL_SCHEMES

        gateway_schemes = GatewayValidator.ALLOWED_URL_SCHEMES
        assert set(_ALLOWED_URL_SCHEMES) == set(gateway_schemes), f"Framework schemes {_ALLOWED_URL_SCHEMES} differ from gateway {gateway_schemes}"

    def test_dangerous_url_patterns_parity(self):
        """Framework dangerous URL patterns must match the gateway's patterns."""
        from mcpgateway.common.validators import _DANGEROUS_URL_PATTERNS as gateway_patterns
        from mcpgateway.plugins.framework.validators import _DANGEROUS_URL_PATTERNS as framework_patterns

        gateway_set = {p.pattern for p in gateway_patterns}
        framework_set = {p.pattern for p in framework_patterns}
        assert gateway_set == framework_set, f"Framework patterns {framework_set} differ from gateway {gateway_set}"

    def test_dangerous_html_pattern_parity(self):
        """Framework HTML XSS pattern must match the gateway's pattern (ignoring inline flags)."""
        import re

        from mcpgateway.config import settings as gw_settings
        from mcpgateway.plugins.framework.validators import _DANGEROUS_HTML_PATTERN

        # Strip inline flags like (?i) for comparison — both compile with IGNORECASE
        gw_pattern = re.sub(r"^\(\?[aiLmsux]+\)", "", gw_settings.validation_dangerous_html_pattern)
        assert _DANGEROUS_HTML_PATTERN.pattern == gw_pattern, (
            f"Framework HTML pattern differs from gateway: "
            f"{_DANGEROUS_HTML_PATTERN.pattern!r} vs {gw_pattern!r}"
        )

    def test_dangerous_js_pattern_parity(self):
        """Framework JS/event-handler pattern must match the gateway's pattern (ignoring inline flags)."""
        import re

        from mcpgateway.config import settings as gw_settings
        from mcpgateway.plugins.framework.validators import _DANGEROUS_JS_PATTERN

        # Strip inline flags like (?i) for comparison — both compile with IGNORECASE
        gw_pattern = re.sub(r"^\(\?[aiLmsux]+\)", "", gw_settings.validation_dangerous_js_pattern)
        assert _DANGEROUS_JS_PATTERN.pattern == gw_pattern, (
            f"Framework JS pattern differs from gateway: "
            f"{_DANGEROUS_JS_PATTERN.pattern!r} vs {gw_pattern!r}"
        )

    def test_blocked_networks_cover_standard_private_ranges(self):
        """Framework SSRF blocked networks must include standard private/reserved ranges."""
        from mcpgateway.plugins.framework.validators import _BLOCKED_NETWORKS

        blocked = {str(n) for n in _BLOCKED_NETWORKS}
        expected = {"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "169.254.0.0/16"}
        assert expected.issubset(blocked), f"Missing standard private ranges: {expected - blocked}"


class TestUrlHtmlJsPatternBlocking:
    """Tests for HTML/JS XSS pattern detection within validate_url."""

    def test_html_tag_in_url_rejected(self):
        with pytest.raises(ValueError, match="HTML tags"):
            SecurityValidator.validate_url("https://example.com/<script>alert(1)</script>")

    def test_js_event_handler_in_url_rejected(self):
        with pytest.raises(ValueError, match="script patterns"):
            SecurityValidator.validate_url("https://example.com/page?q=onclick=alert(1)")


class TestDangerousPatternDetection:
    """Functional tests for HTML/JS XSS pattern detection."""

    @pytest.mark.parametrize(
        "html",
        [
            "<script>alert(1)</script>",
            "<SCRIPT>alert(1)</SCRIPT>",
            "<iframe src='evil'>",
            "<object data='x'>",
            "<embed src='x'>",
            "<img src=x onerror=alert(1)>",
            "<svg onload=alert(1)>",
            "<form action='evil'>",
        ],
    )
    def test_dangerous_html_pattern_matches(self, html):
        from mcpgateway.plugins.framework.validators import _DANGEROUS_HTML_PATTERN

        assert _DANGEROUS_HTML_PATTERN.search(html), f"Pattern should match: {html!r}"

    @pytest.mark.parametrize(
        "safe",
        [
            "plain text with no tags",
            "<p>paragraph</p>",
            "<div>content</div>",
            "<span>inline</span>",
        ],
    )
    def test_dangerous_html_pattern_ignores_safe_tags(self, safe):
        from mcpgateway.plugins.framework.validators import _DANGEROUS_HTML_PATTERN

        assert not _DANGEROUS_HTML_PATTERN.search(safe), f"Pattern should not match: {safe!r}"

    @pytest.mark.parametrize(
        "js",
        [
            "javascript:alert(1)",
            "vbscript:MsgBox",
            ' onclick=alert(1)',
            ' onload=evil()',
            '<script src="x">',
        ],
    )
    def test_dangerous_js_pattern_matches(self, js):
        from mcpgateway.plugins.framework.validators import _DANGEROUS_JS_PATTERN

        assert _DANGEROUS_JS_PATTERN.search(js), f"Pattern should match: {js!r}"

    @pytest.mark.parametrize(
        "safe",
        [
            "just some text",
            "function call()",
            "data = 42",
        ],
    )
    def test_dangerous_js_pattern_ignores_safe_input(self, safe):
        from mcpgateway.plugins.framework.validators import _DANGEROUS_JS_PATTERN

        assert not _DANGEROUS_JS_PATTERN.search(safe), f"Pattern should not match: {safe!r}"
