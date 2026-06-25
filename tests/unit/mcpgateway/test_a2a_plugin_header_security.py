# -*- coding: utf-8 -*-
"""Tests for plugin header modification security (PR #5183 review fix).

Validates that plugin-returned headers in modified_payload.headers are
subject to the same filtering and whitelist enforcement as inbound headers.

This prevents malicious or compromised plugins from injecting sensitive
headers into downstream A2A requests.
"""

from unittest.mock import MagicMock

import pytest

from mcpgateway.db import A2AAgent
from mcpgateway.services.a2a_service import A2AAgentService


@pytest.fixture
def mock_agent_with_whitelist():
    """A2A agent with passthrough_headers whitelist."""
    agent = MagicMock(spec=A2AAgent)
    agent.name = "test-agent"
    agent.passthrough_headers = ["X-Custom-Header", "X-Request-Id"]
    agent.use_oauth = False
    return agent


@pytest.fixture
def a2a_service():
    """A2AAgentService instance for testing."""
    return A2AAgentService()


class TestPluginHeaderSecurityRefiltering:
    """Test suite for plugin-returned header security."""

    def test_plugin_cannot_inject_authorization_when_flag_disabled(self, a2a_service, mock_agent_with_whitelist):
        """Plugin-returned Authorization header must be filtered when flag is disabled."""
        # Setup: Plugin tries to inject Authorization header
        plugin_returned = {
            "Authorization": "Bearer malicious-token",
            "X-Custom-Header": "safe-value",
        }

        result = a2a_service._refilter_plugin_headers(
            plugin_headers=plugin_returned,
            agent=mock_agent_with_whitelist,
            feature_flag_enabled=False,
        )

        # Assert: Authorization stripped, safe header preserved
        assert "Authorization" not in result
        assert result.get("X-Custom-Header") == "safe-value"

    def test_plugin_cannot_inject_api_key_when_flag_disabled(self, a2a_service, mock_agent_with_whitelist):
        """Plugin-returned X-Api-Key header must be filtered when flag is disabled."""
        plugin_returned = {
            "X-Api-Key": "malicious-key",  # pragma: allowlist secret
            "X-Request-Id": "req-123",
        }

        result = a2a_service._refilter_plugin_headers(
            plugin_headers=plugin_returned,
            agent=mock_agent_with_whitelist,
            feature_flag_enabled=False,
        )

        assert "X-Api-Key" not in result
        assert result.get("X-Request-Id") == "req-123"

    def test_plugin_cannot_inject_multiple_sensitive_headers(self, a2a_service, mock_agent_with_whitelist):
        """All sensitive header patterns must be blocked."""
        plugin_returned = {
            "Authorization": "Bearer token",
            "X-Api-Key": "key123",  # pragma: allowlist secret
            "Cookie": "session=abc",
            "Proxy-Authorization": "Basic dGVzdA==",
            "X-Auth-Token": "token456",
            "X-Custom-Header": "safe",  # This should pass
        }

        result = a2a_service._refilter_plugin_headers(
            plugin_headers=plugin_returned,
            agent=mock_agent_with_whitelist,
            feature_flag_enabled=False,
        )

        # All sensitive headers blocked
        assert "Authorization" not in result
        assert "X-Api-Key" not in result
        assert "Cookie" not in result
        assert "Proxy-Authorization" not in result
        assert "X-Auth-Token" not in result

        # Safe whitelisted header preserved
        assert result.get("X-Custom-Header") == "safe"

    def test_plugin_cannot_bypass_passthrough_whitelist(self, a2a_service, mock_agent_with_whitelist):
        """Plugin-returned headers must respect agent's passthrough_headers whitelist."""
        # Setup: Plugin returns header NOT in whitelist
        plugin_returned = {
            "X-Custom-Header": "allowed",
            "X-Not-Whitelisted": "should-be-blocked",
            "X-Request-Id": "req-456",
        }

        result = a2a_service._refilter_plugin_headers(
            plugin_headers=plugin_returned,
            agent=mock_agent_with_whitelist,
            feature_flag_enabled=False,
        )

        # Assert: Only whitelisted headers present
        assert result.get("X-Custom-Header") == "allowed"
        assert result.get("X-Request-Id") == "req-456"
        assert "X-Not-Whitelisted" not in result

    def test_plugin_can_modify_whitelisted_headers_when_flag_enabled(self, a2a_service, mock_agent_with_whitelist):
        """Plugins can modify whitelisted sensitive headers when flag is enabled."""
        plugin_returned = {
            "Authorization": "Bearer modified-by-plugin",
            "X-Custom-Header": "also-modified",
        }

        # Setup: Add Authorization to whitelist AND enable flag
        mock_agent_with_whitelist.passthrough_headers = ["X-Custom-Header", "Authorization"]

        result = a2a_service._refilter_plugin_headers(
            plugin_headers=plugin_returned,
            agent=mock_agent_with_whitelist,
            feature_flag_enabled=True,  # Flag ENABLED
        )

        # Assert: Both headers preserved when flag enabled + whitelisted
        assert result.get("Authorization") == "Bearer modified-by-plugin"
        assert result.get("X-Custom-Header") == "also-modified"

    def test_plugin_sensitive_header_blocked_even_when_whitelisted_if_flag_disabled(self, a2a_service, mock_agent_with_whitelist):
        """Sensitive headers blocked even if whitelisted when flag is disabled."""
        plugin_returned = {
            "Authorization": "Bearer token",
        }

        # Add Authorization to whitelist (but flag is disabled)
        mock_agent_with_whitelist.passthrough_headers = ["X-Custom-Header", "Authorization"]

        result = a2a_service._refilter_plugin_headers(
            plugin_headers=plugin_returned,
            agent=mock_agent_with_whitelist,
            feature_flag_enabled=False,  # Flag DISABLED
        )

        # Assert: Authorization blocked because flag is disabled
        # (Layer 1 filtering happens before Layer 2 whitelist)
        assert "Authorization" not in result

    def test_empty_whitelist_blocks_all_plugin_headers(self, a2a_service):
        """Agent with empty passthrough_headers blocks all plugin-returned headers."""
        agent = MagicMock(spec=A2AAgent)
        agent.name = "no-whitelist-agent"
        agent.passthrough_headers = []  # Empty whitelist

        plugin_returned = {
            "X-Custom-Header": "value",
            "X-Request-Id": "req-789",
        }

        result = a2a_service._refilter_plugin_headers(
            plugin_headers=plugin_returned,
            agent=agent,
            feature_flag_enabled=False,
        )

        # Assert: All headers blocked (whitelist is empty)
        assert len(result) == 0

    def test_case_insensitive_whitelist_matching(self, a2a_service, mock_agent_with_whitelist):
        """Whitelist matching should be case-insensitive."""
        plugin_returned = {
            "x-custom-header": "lowercase",  # lowercase key
            "X-REQUEST-ID": "uppercase",  # uppercase key
        }

        # Whitelist has mixed case: ["X-Custom-Header", "X-Request-Id"]

        result = a2a_service._refilter_plugin_headers(
            plugin_headers=plugin_returned,
            agent=mock_agent_with_whitelist,
            feature_flag_enabled=False,
        )

        # Assert: Both variants allowed (case-insensitive match)
        assert "x-custom-header" in result
        assert "X-REQUEST-ID" in result

    def test_none_whitelist_allows_no_headers(self, a2a_service):
        """Agent with None passthrough_headers allows no plugin headers."""
        agent = MagicMock(spec=A2AAgent)
        agent.name = "none-whitelist-agent"
        agent.passthrough_headers = None  # No whitelist configured

        plugin_returned = {
            "X-Custom-Header": "value",
        }

        result = a2a_service._refilter_plugin_headers(
            plugin_headers=plugin_returned,
            agent=agent,
            feature_flag_enabled=False,
        )

        # Assert: No headers pass through without whitelist
        assert len(result) == 0

    def test_host_header_blocked_when_flag_disabled(self, a2a_service, mock_agent_with_whitelist):
        """Host header is blocked when flag is disabled even if whitelisted."""
        # Add Host to whitelist
        mock_agent_with_whitelist.passthrough_headers = ["X-Custom-Header", "Host"]

        plugin_returned = {
            "Host": "evil.example.com",
            "X-Custom-Header": "safe",
        }

        result = a2a_service._refilter_plugin_headers(
            plugin_headers=plugin_returned,
            agent=mock_agent_with_whitelist,
            feature_flag_enabled=False,  # Flag disabled
        )

        # Host filtered when flag is disabled
        assert "Host" not in result
        assert result.get("X-Custom-Header") == "safe"

    def test_host_header_allowed_when_flag_enabled_and_whitelisted(self, a2a_service, mock_agent_with_whitelist):
        """Host header passes through when flag is enabled AND whitelisted."""
        # Add Host to whitelist
        mock_agent_with_whitelist.passthrough_headers = ["X-Custom-Header", "Host"]

        plugin_returned = {
            "Host": "allowed.example.com",
            "X-Custom-Header": "safe",
        }

        result = a2a_service._refilter_plugin_headers(
            plugin_headers=plugin_returned,
            agent=mock_agent_with_whitelist,
            feature_flag_enabled=True,  # Flag enabled
        )

        # Host allowed when flag enabled + whitelisted (this is the feature's purpose)
        assert result.get("Host") == "allowed.example.com"
        assert result.get("X-Custom-Header") == "safe"

    def test_empty_plugin_headers_return_empty(self, a2a_service, mock_agent_with_whitelist):
        """Empty plugin headers should return empty dict."""
        plugin_returned = {}

        result = a2a_service._refilter_plugin_headers(
            plugin_headers=plugin_returned,
            agent=mock_agent_with_whitelist,
            feature_flag_enabled=False,
        )

        assert result == {}

    def test_cookie_blocked_when_flag_disabled(self, a2a_service, mock_agent_with_whitelist):
        """Cookie and Set-Cookie headers blocked when flag disabled."""
        mock_agent_with_whitelist.passthrough_headers = ["Cookie", "Set-Cookie", "X-Custom-Header"]

        plugin_returned = {
            "Cookie": "session=abc",
            "Set-Cookie": "token=xyz",
            "X-Custom-Header": "safe",
        }

        result = a2a_service._refilter_plugin_headers(
            plugin_headers=plugin_returned,
            agent=mock_agent_with_whitelist,
            feature_flag_enabled=False,  # Flag disabled
        )

        # Cookies filtered when flag disabled
        assert "Cookie" not in result
        assert "Set-Cookie" not in result
        assert result.get("X-Custom-Header") == "safe"

    def test_cookie_allowed_when_flag_enabled_and_whitelisted(self, a2a_service, mock_agent_with_whitelist):
        """Cookie headers pass through when flag enabled AND whitelisted."""
        mock_agent_with_whitelist.passthrough_headers = ["Cookie", "X-Custom-Header"]

        plugin_returned = {
            "Cookie": "session=abc",
            "X-Custom-Header": "safe",
        }

        result = a2a_service._refilter_plugin_headers(
            plugin_headers=plugin_returned,
            agent=mock_agent_with_whitelist,
            feature_flag_enabled=True,  # Flag enabled
        )

        # Cookie allowed when flag enabled + whitelisted
        assert result.get("Cookie") == "session=abc"
        assert result.get("X-Custom-Header") == "safe"

    def test_prepare_header_flows_with_flag_enabled(self, monkeypatch):
        """Downstream headers include sensitive headers when flag enabled (line 1966 coverage)."""
        from mcpgateway import config
        from mcpgateway.services.a2a_service import A2AAgentService

        monkeypatch.setattr(config.settings, "enable_sensitive_header_passthrough", True)

        request_headers = {
            "authorization": "Bearer token",  # Lowercase as it would be in reality
            "x-custom-header": "value",
        }
        whitelist = ["Authorization", "X-Custom-Header"]

        plugin_headers, downstream_headers = A2AAgentService._prepare_header_flows(
            request_headers=request_headers,
            agent_passthrough_headers=whitelist,
        )

        # Plugin headers never include sensitive
        assert "authorization" not in plugin_headers
        assert plugin_headers.get("x-custom-header") == "value"

        # Downstream DOES include sensitive when flag enabled (line 1966)
        assert downstream_headers.get("authorization") == "Bearer token"
        assert downstream_headers.get("x-custom-header") == "value"
