# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_passthrough_headers.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for HTTP header passthrough functionality.
This module contains comprehensive unit tests for the passthrough_headers utility
module, covering all scenarios including configuration priorities, conflict
detection, case sensitivity, and security features.
"""

# Standard
import logging
from unittest.mock import Mock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway.cache.global_config_cache import global_config_cache
from mcpgateway.db import Gateway as DbGateway
from mcpgateway.db import GlobalConfig
from mcpgateway.utils.passthrough_headers import get_passthrough_headers


class TestPassthroughHeaders:
    """Test suite for HTTP header passthrough functionality."""

    def setup_method(self):
        """Clear the global config cache before each test to ensure isolation."""
        global_config_cache.invalidate()

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_basic_header_passthrough_global_config(self, mock_settings):
        """Test basic header passthrough with global configuration."""
        mock_settings.enable_header_passthrough = True

        # Mock database and global config
        mock_db = Mock()
        mock_global_config = Mock(spec=GlobalConfig)
        mock_global_config.passthrough_headers = ["X-Tenant-Id", "X-Trace-Id"]
        mock_db.query.return_value.first.return_value = mock_global_config

        request_headers = {"x-tenant-id": "acme-corp", "x-trace-id": "trace-456", "user-agent": "TestClient/1.0"}  # Not in allowed headers
        base_headers = {"Content-Type": "application/json"}

        result = get_passthrough_headers(request_headers, base_headers, mock_db)

        expected = {"Content-Type": "application/json", "X-Tenant-Id": "acme-corp", "X-Trace-Id": "trace-456"}
        assert result == expected

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_gateway_specific_override(self, mock_settings):
        """Test that gateway-specific headers override global configuration."""
        mock_settings.enable_header_passthrough = True

        mock_db = Mock()
        mock_global_config = Mock(spec=GlobalConfig)
        mock_global_config.passthrough_headers = ["X-Tenant-Id", "X-Trace-Id"]
        mock_db.query.return_value.first.return_value = mock_global_config

        # Gateway with custom headers
        mock_gateway = Mock(spec=DbGateway)
        mock_gateway.passthrough_headers = ["X-Custom-Header"]
        mock_gateway.auth_type = None

        request_headers = {"x-custom-header": "custom-value", "x-tenant-id": "should-be-ignored", "x-trace-id": "also-ignored"}  # Not in gateway config
        base_headers = {"Content-Type": "application/json"}

        result = get_passthrough_headers(request_headers, base_headers, mock_db, mock_gateway)

        expected = {"Content-Type": "application/json", "X-Custom-Header": "custom-value"}
        assert result == expected

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_authorization_conflict_basic_auth(self, mock_settings, caplog):
        """Test that Authorization header is blocked when gateway uses basic auth."""
        mock_settings.enable_header_passthrough = True

        mock_db = Mock()
        mock_global_config = Mock(spec=GlobalConfig)
        mock_global_config.passthrough_headers = ["Authorization", "X-Tenant-Id"]
        mock_db.query.return_value.first.return_value = mock_global_config

        mock_gateway = Mock(spec=DbGateway)
        mock_gateway.passthrough_headers = ["Authorization", "X-Tenant-Id"]
        mock_gateway.auth_type = "basic"
        mock_gateway.name = "test-gateway"

        request_headers = {"authorization": "Bearer should-be-blocked", "x-tenant-id": "acme-corp"}
        base_headers = {"Content-Type": "application/json"}

        with caplog.at_level(logging.WARNING):
            result = get_passthrough_headers(request_headers, base_headers, mock_db, mock_gateway)

        # Authorization should be blocked, X-Tenant-Id should pass through
        expected = {"Content-Type": "application/json", "X-Tenant-Id": "acme-corp"}
        assert result == expected

        # Check warning was logged
        assert any("Skipping Authorization header passthrough due to basic auth" in record.message for record in caplog.records)

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_authorization_conflict_bearer_auth(self, mock_settings, caplog):
        """Test that Authorization header is blocked when gateway uses bearer auth."""
        mock_settings.enable_header_passthrough = True

        mock_db = Mock()
        mock_global_config = Mock(spec=GlobalConfig)
        mock_global_config.passthrough_headers = ["Authorization"]
        mock_db.query.return_value.first.return_value = mock_global_config

        mock_gateway = Mock(spec=DbGateway)
        mock_gateway.passthrough_headers = None  # Use global
        mock_gateway.auth_type = "bearer"
        mock_gateway.name = "bearer-gateway"

        request_headers = {"authorization": "Bearer should-be-blocked"}
        base_headers = {"Content-Type": "application/json"}

        with caplog.at_level(logging.WARNING):
            result = get_passthrough_headers(request_headers, base_headers, mock_db, mock_gateway)

        # Only base headers should remain
        expected = {"Content-Type": "application/json"}
        assert result == expected

        # Check warning was logged
        assert any("Skipping Authorization header passthrough due to bearer auth" in record.message for record in caplog.records)

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_base_header_conflict_prevention(self, mock_settings, caplog):
        """Test that request headers don't override base headers."""
        mock_settings.enable_header_passthrough = True
        mock_settings.enable_overwrite_base_headers = False

        mock_db = Mock()
        mock_global_config = Mock(spec=GlobalConfig)
        mock_global_config.passthrough_headers = ["Content-Type", "X-Tenant-Id"]
        mock_db.query.return_value.first.return_value = mock_global_config

        request_headers = {"content-type": "text/plain", "x-tenant-id": "acme-corp"}  # Conflicts with base header  # Should pass through
        base_headers = {"Content-Type": "application/json"}

        with caplog.at_level(logging.WARNING):
            result = get_passthrough_headers(request_headers, base_headers, mock_db)

        # Base header preserved, tenant ID added
        expected = {"Content-Type": "application/json", "X-Tenant-Id": "acme-corp"}
        assert result == expected

        # Check conflict warning was logged
        assert any("conflicts with pre-defined headers" in record.message for record in caplog.records)

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_case_insensitive_header_matching(self, mock_settings):
        """Test that header matching works with lowercase request headers."""
        mock_settings.enable_header_passthrough = True

        mock_db = Mock()
        mock_global_config = Mock(spec=GlobalConfig)
        mock_global_config.passthrough_headers = ["X-Tenant-ID", "Authorization"]
        mock_db.query.return_value.first.return_value = mock_global_config

        # Request headers are expected to be normalized to lowercase
        request_headers = {"x-tenant-id": "mixed-case-value", "authorization": "bearer lowercase-header"}  # Lowercase key
        base_headers: dict[str, str] = {}

        result = get_passthrough_headers(request_headers, base_headers, mock_db)

        # Headers should preserve config case in output keys
        expected = {"X-Tenant-ID": "mixed-case-value", "Authorization": "bearer lowercase-header"}
        assert result == expected

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_missing_request_headers(self, mock_settings, caplog):
        """Test behavior when configured headers are missing from request."""
        mock_settings.enable_header_passthrough = True

        mock_db = Mock()
        mock_global_config = Mock(spec=GlobalConfig)
        mock_global_config.passthrough_headers = ["X-Missing", "X-Present"]
        mock_db.query.return_value.first.return_value = mock_global_config

        request_headers = {"x-present": "present-value"}
        base_headers = {"Content-Type": "application/json"}

        with caplog.at_level(logging.WARNING):
            result = get_passthrough_headers(request_headers, base_headers, mock_db)

        # Only present header should be included
        expected = {"Content-Type": "application/json", "X-Present": "present-value"}
        assert result == expected

        # Check debug message for missing header
        with caplog.at_level(logging.DEBUG, logger="mcpgateway.utils.passthrough_headers"):
            # Re-run to capture debug messages
            result = get_passthrough_headers(request_headers, base_headers, mock_db)

        assert any("X-Missing not found in request headers" in record.message for record in caplog.records)

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_empty_allowed_headers(self, mock_settings):
        """Test behavior with empty allowed headers configuration."""
        mock_settings.enable_header_passthrough = True

        mock_db = Mock()
        mock_global_config = Mock(spec=GlobalConfig)
        mock_global_config.passthrough_headers = []
        mock_db.query.return_value.first.return_value = mock_global_config

        request_headers = {"x-tenant-id": "should-be-ignored"}
        base_headers = {"Content-Type": "application/json"}

        result = get_passthrough_headers(request_headers, base_headers, mock_db)

        # Only base headers should remain
        expected = {"Content-Type": "application/json"}
        assert result == expected

    def test_none_allowed_headers(self):
        """Test behavior when allowed headers is None."""
        mock_db = Mock()
        mock_global_config = Mock(spec=GlobalConfig)
        mock_global_config.passthrough_headers = None
        mock_db.query.return_value.first.return_value = mock_global_config

        request_headers = {"x-tenant-id": "should-be-ignored"}
        base_headers = {"Content-Type": "application/json"}

        # Mock settings fallback
        with patch("mcpgateway.utils.passthrough_headers.settings") as mock_settings:
            mock_settings.default_passthrough_headers = ["X-Default"]

            result = get_passthrough_headers(request_headers, base_headers, mock_db)

        # Should fall back to settings, but request doesn't have X-Default
        expected = {"Content-Type": "application/json"}
        assert result == expected

    def test_no_global_config_fallback_to_settings(self):
        """Test fallback to settings when no global config exists."""
        mock_db = Mock()
        mock_db.query.return_value.first.return_value = None  # No global config

        request_headers = {"x-default": "default-value"}
        base_headers = {"Content-Type": "application/json"}

        # Mock settings fallback
        with patch("mcpgateway.utils.passthrough_headers.settings") as mock_settings:
            mock_settings.default_passthrough_headers = ["X-Default"]

            result = get_passthrough_headers(request_headers, base_headers, mock_db)

        expected = {"Content-Type": "application/json", "X-Default": "default-value"}
        assert result == expected

    def test_empty_request_headers(self):
        """Test behavior with empty request headers."""
        mock_db = Mock()
        mock_global_config = Mock(spec=GlobalConfig)
        mock_global_config.passthrough_headers = ["X-Tenant-Id"]
        mock_db.query.return_value.first.return_value = mock_global_config

        request_headers: dict[str, str] = {}
        base_headers = {"Content-Type": "application/json"}

        result = get_passthrough_headers(request_headers, base_headers, mock_db)

        # Only base headers should remain
        expected = {"Content-Type": "application/json"}
        assert result == expected

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_no_auth_gateway_passes_authorization_when_feature_disabled(self, mock_settings):
        """When gateway.auth_type == 'none', the client's Authorization header
        should be passed through even if ENABLE_HEADER_PASSTHROUGH is False.
        This behavior is handled before the main allowlist processing.
        """
        # Feature disabled globally
        mock_settings.enable_header_passthrough = False

        mock_db = Mock()
        # No global config needed for this early path
        mock_db.query.return_value.first.return_value = None

        request_headers = {"authorization": "Bearer client-token"}
        base_headers: dict[str, str] = {}

        mock_gateway = Mock(spec=DbGateway)
        mock_gateway.passthrough_headers = None
        mock_gateway.auth_type = "none"

        result = get_passthrough_headers(request_headers, base_headers, mock_db, mock_gateway)

        # Authorization should be present because gateway is configured with auth_type 'none'
        assert result.get("Authorization") == "Bearer client-token"

    def test_none_request_headers(self):
        """Test behavior with None request headers."""
        mock_db = Mock()
        mock_global_config = Mock(spec=GlobalConfig)
        mock_global_config.passthrough_headers = ["X-Tenant-Id"]
        mock_db.query.return_value.first.return_value = mock_global_config

        request_headers = None
        base_headers = {"Content-Type": "application/json"}

        result = get_passthrough_headers(request_headers, base_headers, mock_db) # type: ignore[arg-type]

        # Only base headers should remain
        expected = {"Content-Type": "application/json"}
        assert result == expected

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_base_headers_not_modified(self, mock_settings):
        """Test that original base_headers dictionary is not modified."""
        mock_settings.enable_header_passthrough = True

        mock_db = Mock()
        mock_global_config = Mock(spec=GlobalConfig)
        mock_global_config.passthrough_headers = ["X-Tenant-Id"]
        mock_db.query.return_value.first.return_value = mock_global_config

        request_headers = {"x-tenant-id": "acme-corp"}
        base_headers = {"Content-Type": "application/json"}
        original_base = base_headers.copy()

        result = get_passthrough_headers(request_headers, base_headers, mock_db)

        # Original base_headers should not be modified
        assert base_headers == original_base

        # Result should include both base and passthrough headers
        assert "Content-Type" in result
        assert "X-Tenant-Id" in result

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_multiple_auth_type_conflicts(self, mock_settings, caplog):
        """Test various auth type conflict scenarios."""
        mock_settings.enable_header_passthrough = True

        mock_db = Mock()
        mock_global_config = Mock(spec=GlobalConfig)
        mock_global_config.passthrough_headers = ["Authorization"]
        mock_db.query.return_value.first.return_value = mock_global_config

        request_headers = {"authorization": "Bearer token"}
        base_headers: dict[str, str] = {}

        # Test with different auth types. Include the string "none" which should
        # allow passthrough of the client's Authorization header (special-case handled
        # before the main passthrough allowlist logic).
        auth_types = ["basic", "bearer", "api-key", None, "none"]

        for auth_type in auth_types:
            caplog.clear()
            mock_gateway = Mock(spec=DbGateway)
            mock_gateway.passthrough_headers = None
            mock_gateway.auth_type = auth_type
            mock_gateway.name = f"gateway-{auth_type or 'none'}"

            with caplog.at_level(logging.WARNING):
                result = get_passthrough_headers(request_headers, base_headers, mock_db, mock_gateway)

            if auth_type in ["basic", "bearer"]:
                # Authorization should be blocked
                assert "Authorization" not in result
                assert any("Skipping Authorization header passthrough" in record.message for record in caplog.records)
            else:
                # Authorization should pass through
                assert result.get("Authorization") == "Bearer token"

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_complex_mixed_scenario(self, mock_settings):
        """Test complex scenario with multiple headers, conflicts, and overrides."""
        mock_settings.enable_header_passthrough = True

        mock_db = Mock()
        mock_global_config = Mock(spec=GlobalConfig)
        mock_global_config.passthrough_headers = ["Authorization", "X-Global", "X-Conflict"]
        mock_db.query.return_value.first.return_value = mock_global_config

        mock_gateway = Mock(spec=DbGateway)
        mock_gateway.passthrough_headers = ["X-Gateway", "X-Conflict", "Authorization"]
        mock_gateway.auth_type = "basic"  # Will block Authorization
        mock_gateway.name = "complex-gateway"

        request_headers = {
            "authorization": "Bearer token",  # Blocked by basic auth
            "x-global": "global-value",  # Not in gateway config, ignored
            "x-gateway": "gateway-value",  # Should pass through
            "x-conflict": "conflict-value",  # Should pass through (in both configs)
            "x-random": "random-value",  # Not configured, ignored
        }
        base_headers = {"Content-Type": "application/json", "User-Agent": "MCPGateway/1.0"}

        result = get_passthrough_headers(request_headers, base_headers, mock_db, mock_gateway)

        expected = {"Content-Type": "application/json", "User-Agent": "MCPGateway/1.0", "X-Gateway": "gateway-value", "X-Conflict": "conflict-value"}
        assert result == expected

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_database_query_called_correctly(self, mock_settings):
        """Test that database is queried correctly for GlobalConfig."""
        mock_settings.enable_header_passthrough = True

        mock_db = Mock()
        mock_global_config = Mock(spec=GlobalConfig)
        mock_global_config.passthrough_headers = []
        mock_db.query.return_value.first.return_value = mock_global_config

        get_passthrough_headers({}, {}, mock_db)

        # Verify database was queried for GlobalConfig
        mock_db.query.assert_called_once_with(GlobalConfig)
        mock_db.query.return_value.first.assert_called_once()

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_logging_levels(self, mock_settings, caplog):
        """Test that appropriate log levels are used for different scenarios."""
        mock_settings.enable_header_passthrough = True
        mock_settings.enable_overwrite_base_headers = False

        mock_db = Mock()
        mock_global_config = Mock(spec=GlobalConfig)
        mock_global_config.passthrough_headers = ["X-Missing", "Authorization", "X-Conflict"]
        mock_db.query.return_value.first.return_value = mock_global_config

        mock_gateway = Mock(spec=DbGateway)
        mock_gateway.passthrough_headers = None
        mock_gateway.auth_type = "basic"
        mock_gateway.name = "test-gateway"

        request_headers = {"authorization": "Bearer token", "x-conflict": "request-value"}  # Will be blocked by basic auth  # Will conflict with base header
        base_headers = {"X-Conflict": "base-value"}  # Conflicts with x-conflict

        with caplog.at_level(logging.WARNING):
            get_passthrough_headers(request_headers, base_headers, mock_db, mock_gateway)

        # Should have warnings for: missing header, auth conflict, base header conflict
        warning_messages = [record.message for record in caplog.records if record.levelno == logging.WARNING]

        assert len(warning_messages) == 2  # Only auth conflict and base header conflict
        assert any("due to basic auth" in msg for msg in warning_messages)
        assert any("conflicts with pre-defined headers" in msg for msg in warning_messages)

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_enable_overwrite_base_headers(self, mock_settings):
        """Test that enable_overwrite_base_headers allows overriding base headers."""
        mock_settings.enable_header_passthrough = True
        mock_settings.enable_overwrite_base_headers = True  # Enable override
        mock_settings.default_passthrough_headers = ["Content-Type", "X-Tenant-Id"]

        mock_db = Mock()
        mock_db.query.return_value.first.return_value = None

        request_headers = {"content-type": "text/plain", "x-tenant-id": "acme-corp"}
        base_headers = {"Content-Type": "application/json", "User-Agent": "MCPGateway"}

        with patch("mcpgateway.utils.passthrough_headers.logger") as mock_logger:
            result = get_passthrough_headers(request_headers, base_headers, mock_db)

        # Should override Content-Type and add X-Tenant-Id
        expected = {"Content-Type": "text/plain", "User-Agent": "MCPGateway", "X-Tenant-Id": "acme-corp"}
        assert result == expected

        # Should log debug message about override being enabled
        mock_logger.debug.assert_any_call("Overwriting base headers is enabled via ENABLE_OVERWRITE_BASE_HEADERS flag")

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_disable_overwrite_base_headers_prevents_conflicts(self, mock_settings, caplog):
        """Test that when overwrite is disabled, base header conflicts are prevented."""
        mock_settings.enable_header_passthrough = True
        mock_settings.enable_overwrite_base_headers = False  # Disable override (default)
        mock_settings.default_passthrough_headers = ["Content-Type", "X-Tenant-Id"]

        mock_db = Mock()
        mock_db.query.return_value.first.return_value = None

        request_headers = {"content-type": "text/plain", "x-tenant-id": "acme-corp"}
        base_headers = {"Content-Type": "application/json", "User-Agent": "MCPGateway"}

        with caplog.at_level(logging.WARNING):
            result = get_passthrough_headers(request_headers, base_headers, mock_db)

        # Should preserve base Content-Type and add X-Tenant-Id
        expected = {"Content-Type": "application/json", "User-Agent": "MCPGateway", "X-Tenant-Id": "acme-corp"}
        assert result == expected

        # Should log warning about conflict
        assert any("conflicts with pre-defined headers" in record.message for record in caplog.records)
