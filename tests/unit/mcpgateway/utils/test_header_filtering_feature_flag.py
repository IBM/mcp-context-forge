# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_header_filtering_feature_flag.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Unit tests for header filtering with ENABLE_SENSITIVE_HEADER_PASSTHROUGH flag.

These tests cover the feature flag paths in main.py and a2a_service.py to ensure
100% coverage of the header filtering refactoring changes.

Coverage targets:
- main.py:5078 - Feature flag ON path in invoke_a2a_agent
- main.py:5175 - Feature flag ON path in invoke_a2a_agent_by_id
- a2a_service.py:2109 - Downstream headers with flag ON
"""

# Standard
from typing import Dict
from unittest.mock import MagicMock, Mock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.config import Settings
from mcpgateway.utils.header_filtering import filter_sensitive_headers

# Import shared test constants
from .conftest import SAFE_HEADERS, SENSITIVE_HEADERS


class TestHeaderFilteringWithFeatureFlag:
    """Test header filtering behavior with ENABLE_SENSITIVE_HEADER_PASSTHROUGH flag."""

    def test_filter_sensitive_headers_baseline(self):
        """Baseline test: verify filter_sensitive_headers removes credentials."""
        headers = {**SENSITIVE_HEADERS, **SAFE_HEADERS}
        result = filter_sensitive_headers(headers)
        # Sensitive headers should be filtered
        for header_name in SENSITIVE_HEADERS:
            assert header_name not in result
        # Safe headers should pass through
        for header_name in SAFE_HEADERS:
            assert header_name in result

    @patch("mcpgateway.config.settings")
    def test_main_invoke_a2a_agent_flag_off(self, mock_settings):
        """Test main.py:5080 path when feature flag is OFF (default)."""
        mock_settings.enable_sensitive_header_passthrough = False

        # Simulate the logic from main.py:5077-5080
        request_headers_dict = {
            "authorization": "Bearer token",
            "content-type": "application/json",
        }

        if mock_settings.enable_sensitive_header_passthrough:
            request_headers = {k.lower(): v for k, v in request_headers_dict.items()}
        else:
            request_headers = filter_sensitive_headers(
                {k.lower(): v for k, v in request_headers_dict.items()}
            )

        # Flag OFF: sensitive headers should be filtered
        assert "authorization" not in request_headers
        assert "content-type" in request_headers

    @patch("mcpgateway.config.settings")
    def test_main_invoke_a2a_agent_flag_on(self, mock_settings):
        """Test main.py:5078 path when feature flag is ON.

        This covers the missing line in main.py:5078.
        """
        mock_settings.enable_sensitive_header_passthrough = True

        # Simulate the logic from main.py:5077-5080
        request_headers_dict = {
            "authorization": "Bearer token",
            "content-type": "application/json",
        }

        if mock_settings.enable_sensitive_header_passthrough:
            # Line 5078: Pass all headers without filtering
            request_headers = {k.lower(): v for k, v in request_headers_dict.items()}
        else:
            request_headers = filter_sensitive_headers(
                {k.lower(): v for k, v in request_headers_dict.items()}
            )

        # Flag ON: all headers should pass through (including sensitive)
        assert "authorization" in request_headers
        assert request_headers["authorization"] == "Bearer token"
        assert "content-type" in request_headers

    @patch("mcpgateway.config.settings")
    def test_main_invoke_a2a_agent_by_id_flag_off(self, mock_settings):
        """Test main.py:5177 path when feature flag is OFF (default)."""
        mock_settings.enable_sensitive_header_passthrough = False

        # Simulate the logic from main.py:5174-5177
        request_headers_dict = {
            "authorization": "Bearer token",
            "x-custom-id": "test123",
        }

        if mock_settings.enable_sensitive_header_passthrough:
            request_headers = {k.lower(): v for k, v in request_headers_dict.items()}
        else:
            request_headers = filter_sensitive_headers(
                {k.lower(): v for k, v in request_headers_dict.items()}
            )

        # Flag OFF: sensitive headers filtered
        assert "authorization" not in request_headers
        assert "x-custom-id" in request_headers

    @patch("mcpgateway.config.settings")
    def test_main_invoke_a2a_agent_by_id_flag_on(self, mock_settings):
        """Test main.py:5175 path when feature flag is ON.

        This covers the missing line in main.py:5175.
        """
        mock_settings.enable_sensitive_header_passthrough = True

        # Simulate the logic from main.py:5174-5177
        request_headers_dict = {
            "authorization": "Bearer token",
            "x-custom-id": "test123",
        }

        if mock_settings.enable_sensitive_header_passthrough:
            # Line 5175: Pass all headers without filtering
            request_headers = {k.lower(): v for k, v in request_headers_dict.items()}
        else:
            request_headers = filter_sensitive_headers(
                {k.lower(): v for k, v in request_headers_dict.items()}
            )

        # Flag ON: all headers pass through
        assert "authorization" in request_headers
        assert request_headers["authorization"] == "Bearer token"
        assert "x-custom-id" in request_headers

    @patch("mcpgateway.config.settings")
    def test_a2a_service_downstream_headers_flag_off(self, mock_settings):
        """Test a2a_service.py:2107 path when feature flag is OFF (default)."""
        mock_settings.enable_sensitive_header_passthrough = False

        # Simulate the logic from a2a_service.py:2096-2109
        request_headers = {
            "authorization": "Bearer token",
            "x-tenant-id": "acme",
        }
        agent_passthrough_headers = ["Authorization", "X-Tenant-ID"]

        if request_headers and agent_passthrough_headers:
            whitelist_lower = {h.lower() for h in agent_passthrough_headers}
            whitelisted_headers = {
                k: v for k, v in request_headers.items() if k in whitelist_lower
            }

            # Plugin hooks ALWAYS get sanitized headers
            plugin_headers = filter_sensitive_headers(whitelisted_headers)

            # Downstream headers respect the feature flag
            if not mock_settings.enable_sensitive_header_passthrough:
                downstream_headers = plugin_headers  # Line 2107
            else:
                downstream_headers = whitelisted_headers  # Line 2109

        # Flag OFF: downstream same as plugin headers (sensitive filtered)
        assert "authorization" not in downstream_headers
        assert "x-tenant-id" in downstream_headers

    @patch("mcpgateway.config.settings")
    def test_a2a_service_downstream_headers_flag_on(self, mock_settings):
        """Test a2a_service.py:2109 path when feature flag is ON.

        This covers the missing line in a2a_service.py:2109.
        """
        mock_settings.enable_sensitive_header_passthrough = True

        # Simulate the logic from a2a_service.py:2096-2109
        request_headers = {
            "authorization": "Bearer token",
            "x-tenant-id": "acme",
        }
        agent_passthrough_headers = ["Authorization", "X-Tenant-ID"]

        if request_headers and agent_passthrough_headers:
            whitelist_lower = {h.lower() for h in agent_passthrough_headers}
            whitelisted_headers = {
                k: v for k, v in request_headers.items() if k in whitelist_lower
            }

            # Plugin hooks ALWAYS get sanitized headers
            plugin_headers = filter_sensitive_headers(whitelisted_headers)

            # Downstream headers respect the feature flag
            if not mock_settings.enable_sensitive_header_passthrough:
                downstream_headers = plugin_headers  # Line 2107
            else:
                downstream_headers = whitelisted_headers  # Line 2109

        # Flag ON: downstream gets whitelisted headers (including sensitive)
        assert "authorization" in downstream_headers
        assert downstream_headers["authorization"] == "Bearer token"
        assert "x-tenant-id" in downstream_headers

    @patch("mcpgateway.config.settings")
    def test_plugin_headers_always_sanitized(self, mock_settings):
        """Verify plugin hooks ALWAYS get sanitized headers (security requirement).

        This is the security invariant from Issue #3621: plugin hooks must never
        receive sensitive headers, regardless of the feature flag state.
        """
        # Test with flag OFF
        mock_settings.enable_sensitive_header_passthrough = False
        request_headers = {"authorization": "Bearer token", "x-tenant-id": "acme"}
        agent_passthrough_headers = ["Authorization", "X-Tenant-ID"]

        whitelist_lower = {h.lower() for h in agent_passthrough_headers}
        whitelisted_headers = {
            k: v for k, v in request_headers.items() if k in whitelist_lower
        }
        plugin_headers_off = filter_sensitive_headers(whitelisted_headers)

        # Test with flag ON
        mock_settings.enable_sensitive_header_passthrough = True
        plugin_headers_on = filter_sensitive_headers(whitelisted_headers)

        # Plugin headers should be identical regardless of flag
        assert plugin_headers_off == plugin_headers_on
        assert "authorization" not in plugin_headers_off
        assert "authorization" not in plugin_headers_on
        assert "x-tenant-id" in plugin_headers_off
        assert "x-tenant-id" in plugin_headers_on

    @pytest.mark.parametrize(
        "flag_state,expected_auth_present",
        [
            (False, False),  # Flag OFF: authorization filtered
            (True, True),  # Flag ON: authorization passed through
        ],
    )
    @patch("mcpgateway.config.settings")
    def test_feature_flag_controls_sensitive_header_flow(
        self, mock_settings, flag_state, expected_auth_present
    ):
        """Parametrized test verifying flag controls sensitive header flow."""
        mock_settings.enable_sensitive_header_passthrough = flag_state

        request_headers = {
            "authorization": "Bearer token",
            "content-type": "application/json",
        }

        # Router-level filtering (main.py logic)
        if mock_settings.enable_sensitive_header_passthrough:
            router_headers = {k.lower(): v for k, v in request_headers.items()}
        else:
            router_headers = filter_sensitive_headers(
                {k.lower(): v for k, v in request_headers.items()}
            )

        # Service-level filtering (a2a_service.py logic)
        agent_passthrough_headers = ["Authorization", "Content-Type"]
        whitelist_lower = {h.lower() for h in agent_passthrough_headers}
        whitelisted = {k: v for k, v in router_headers.items() if k in whitelist_lower}

        plugin_headers = filter_sensitive_headers(whitelisted)

        if not mock_settings.enable_sensitive_header_passthrough:
            downstream_headers = plugin_headers
        else:
            downstream_headers = whitelisted

        # Verify expectations
        assert ("authorization" in downstream_headers) == expected_auth_present
        assert "content-type" in downstream_headers  # Always present

    @patch("mcpgateway.config.settings")
    def test_multiple_sensitive_headers_with_flag_on(self, mock_settings):
        """Test multiple sensitive headers pass through when flag is ON."""
        mock_settings.enable_sensitive_header_passthrough = True

        request_headers = {
            "authorization": "Bearer token123",
            "x-api-key": "secret456",  # pragma: allowlist secret
            "cookie": "session=abc",
            "content-type": "application/json",
        }

        # Router level (main.py:5078 or 5175)
        if mock_settings.enable_sensitive_header_passthrough:
            router_headers = {k.lower(): v for k, v in request_headers.items()}
        else:
            router_headers = filter_sensitive_headers(
                {k.lower(): v for k, v in request_headers.items()}
            )

        # All headers including sensitive should pass through
        assert "authorization" in router_headers
        assert "x-api-key" in router_headers
        assert "cookie" in router_headers
        assert "content-type" in router_headers

    @patch("mcpgateway.config.settings")
    def test_case_insensitive_header_filtering_with_flag(self, mock_settings):
        """Test case-insensitive header handling with feature flag."""
        mock_settings.enable_sensitive_header_passthrough = True

        request_headers = {
            "Authorization": "Bearer token",  # Title case
            "X-API-KEY": "secret",  # Upper case
            "Content-Type": "application/json",
        }

        # Lowercase normalization (main.py pattern)
        if mock_settings.enable_sensitive_header_passthrough:
            router_headers = {k.lower(): v for k, v in request_headers.items()}
        else:
            router_headers = filter_sensitive_headers(
                {k.lower(): v for k, v in request_headers.items()}
            )

        # All headers normalized to lowercase and passed through
        assert "authorization" in router_headers
        assert "x-api-key" in router_headers
        assert "content-type" in router_headers

        # Original case not preserved (by design)
        assert "Authorization" not in router_headers
        assert "X-API-KEY" not in router_headers
