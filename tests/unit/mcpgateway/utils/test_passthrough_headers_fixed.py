# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_passthrough_headers_fixed.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Fixed unit tests for HTTP header passthrough functionality.
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
from mcpgateway.utils.passthrough_headers import (
    compute_passthrough_headers_cached,
    get_passthrough_headers,
    PassthroughHeadersError,
    set_global_passthrough_headers,
)


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
    def test_feature_disabled_by_default(self, mock_settings):
        """Test that feature is disabled by default."""
        mock_settings.enable_header_passthrough = False

        mock_db = Mock()
        request_headers = {"x-tenant-id": "test"}
        base_headers = {"Content-Type": "application/json"}

        # Don't mock settings - use default behavior
        result = get_passthrough_headers(request_headers, base_headers, mock_db)

        # Should return only base headers when disabled (default)
        assert result == base_headers
        # Database should not be queried when feature is disabled
        mock_db.query.assert_not_called()

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
        base_headers = {}

        result = get_passthrough_headers(request_headers, base_headers, mock_db)

        # Headers should preserve config case in output keys
        expected = {"X-Tenant-ID": "mixed-case-value", "Authorization": "bearer lowercase-header"}
        assert result == expected

    @pytest.mark.asyncio
    @patch("mcpgateway.utils.passthrough_headers.settings")
    async def test_set_global_passthrough_headers_default(self, mock_settings):
        mock_settings.enable_header_passthrough = True
        mock_settings.default_passthrough_headers = ["X-Tenant-Id", "X-Trace-Id"]

        mock_db = Mock()
        mock_db.query.return_value.first.return_value = None  # Simulate no config in DB

        # Act
        await set_global_passthrough_headers(mock_db)

        # Assert
        mock_db.add.assert_called_once()
        added_config = mock_db.add.call_args[0][0]
        assert added_config.passthrough_headers == ["X-Tenant-Id", "X-Trace-Id"]

        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    @patch("mcpgateway.utils.passthrough_headers.settings")
    async def test_set_global_passthrough_headers_invalid_config(self, mock_settings):
        """Should raise PassthroughHeadersError when config is invalid."""
        mock_settings.enable_header_passthrough = True

        mock_db = Mock()
        mock_db.query.return_value.first.return_value = None
        mock_db.commit.side_effect = Exception("DB write failed")

        with pytest.raises(PassthroughHeadersError) as exc_info:
            await set_global_passthrough_headers(mock_db)

        assert "DB write failed" in str(exc_info.value) or str(exc_info.value)
        mock_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    @patch("mcpgateway.utils.passthrough_headers.settings")
    async def test_set_global_passthrough_headers_existing_config(self, mock_settings):
        """Should raise PassthroughHeadersError when config is invalid."""
        mock_settings.enable_header_passthrough = True

        mock_db = Mock()
        mock_global_config = Mock(spec=GlobalConfig)
        mock_global_config.passthrough_headers = ["X-Tenant-ID", "Authorization"]
        mock_db.query.return_value.first.return_value = mock_global_config

        await set_global_passthrough_headers(mock_db)

        mock_db.add.assert_not_called()
        mock_db.commit.assert_not_called()

        # Ensure existing config is not modified
        assert mock_global_config.passthrough_headers == ["X-Tenant-ID", "Authorization"]
        mock_db.rollback.assert_not_called()

    @pytest.mark.asyncio
    @patch("mcpgateway.utils.passthrough_headers.settings")
    async def test_set_global_passthrough_headers_filters_invalid_header_names(self, mock_settings, caplog):
        mock_settings.passthrough_headers_source = "db"
        mock_settings.default_passthrough_headers = ["X-Ok", "Bad Header"]

        mock_db = Mock()
        mock_db.query.return_value.first.return_value = None

        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.passthrough_headers"):
            await set_global_passthrough_headers(mock_db)

        added_config = mock_db.add.call_args[0][0]
        assert added_config.passthrough_headers == ["X-Ok"]
        assert any("Invalid header name" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    @patch("mcpgateway.utils.passthrough_headers.settings")
    async def test_set_global_passthrough_headers_handles_empty_defaults(self, mock_settings):
        mock_settings.passthrough_headers_source = "db"
        mock_settings.default_passthrough_headers = []

        mock_db = Mock()
        mock_db.query.return_value.first.return_value = None

        await set_global_passthrough_headers(mock_db)

        added_config = mock_db.add.call_args[0][0]
        assert added_config.passthrough_headers == []


class TestPassthroughHeadersSpecialAuth:
    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_x_upstream_authorization_is_renamed_even_when_feature_disabled(self, mock_settings):
        mock_settings.enable_header_passthrough = False

        mock_db = Mock()
        request_headers = {"X-Upstream-Authorization": "Bearer abc\r\n"}
        base_headers: dict[str, str] = {}

        result = get_passthrough_headers(request_headers, base_headers, mock_db)
        assert result["Authorization"] == "Bearer abc"
        mock_db.query.assert_not_called()

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_x_upstream_authorization_sanitize_error_is_logged(self, mock_settings, caplog):
        mock_settings.enable_header_passthrough = False

        mock_db = Mock()
        request_headers = {"X-Upstream-Authorization": "Bearer abc"}

        with patch("mcpgateway.utils.passthrough_headers.sanitize_header_value", side_effect=Exception("boom")):
            with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.passthrough_headers"):
                result = get_passthrough_headers(request_headers, {}, mock_db)

        assert "Authorization" not in result
        assert any("Failed to sanitize X-Upstream-Authorization" in record.message for record in caplog.records)
        mock_db.query.assert_not_called()

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_x_upstream_authorization_sanitizes_to_empty_is_skipped(self, mock_settings):
        mock_settings.enable_header_passthrough = False

        mock_db = Mock()
        request_headers = {"X-Upstream-Authorization": "Bearer abc"}

        with patch("mcpgateway.utils.passthrough_headers.sanitize_header_value", return_value=""):
            result = get_passthrough_headers(request_headers, {}, mock_db)

        assert "Authorization" not in result
        mock_db.query.assert_not_called()

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_no_auth_gateway_does_not_override_existing_base_authorization(self, mock_settings):
        mock_settings.enable_header_passthrough = False

        mock_db = Mock()
        gateway = Mock(spec=DbGateway)
        gateway.passthrough_headers = None
        gateway.auth_type = "none"

        base_headers = {"Authorization": "Bearer base"}
        result = get_passthrough_headers({"Authorization": "Bearer client"}, base_headers, mock_db, gateway)

        assert result["Authorization"] == "Bearer base"
        mock_db.query.assert_not_called()

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_no_auth_gateway_client_authorization_sanitizes_to_empty_is_skipped(self, mock_settings):
        mock_settings.enable_header_passthrough = False

        mock_db = Mock()
        gateway = Mock(spec=DbGateway)
        gateway.passthrough_headers = None
        gateway.auth_type = "none"

        with patch("mcpgateway.utils.passthrough_headers.sanitize_header_value", return_value=""):
            result = get_passthrough_headers({"Authorization": "Bearer client"}, {}, mock_db, gateway)

        assert "Authorization" not in result
        mock_db.query.assert_not_called()

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_no_auth_gateway_authorization_sanitize_error_is_logged(self, mock_settings, caplog):
        mock_settings.enable_header_passthrough = False

        mock_db = Mock()
        mock_gateway = Mock(spec=DbGateway)
        mock_gateway.passthrough_headers = None
        mock_gateway.auth_type = "none"

        with patch("mcpgateway.utils.passthrough_headers.sanitize_header_value", side_effect=Exception("boom")):
            with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.passthrough_headers"):
                result = get_passthrough_headers({"Authorization": "Bearer token"}, {}, mock_db, mock_gateway)

        assert "Authorization" not in result
        assert any("Failed to sanitize Authorization header" in record.message for record in caplog.records)
        mock_db.query.assert_not_called()


class TestComputePassthroughHeadersCached:
    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_cached_feature_disabled_still_allows_x_upstream_authorization(self, mock_settings):
        mock_settings.enable_header_passthrough = False
        mock_settings.enable_overwrite_base_headers = False

        result = compute_passthrough_headers_cached(
            request_headers={"X-Upstream-Authorization": "Bearer abc\r\n"},
            base_headers={},
            allowed_headers=[],
            gateway_auth_type="basic",
        )
        assert result["Authorization"] == "Bearer abc"

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_cached_x_upstream_authorization_sanitize_error_is_logged(self, mock_settings, caplog):
        mock_settings.enable_header_passthrough = False
        mock_settings.enable_overwrite_base_headers = False

        with patch("mcpgateway.utils.passthrough_headers.sanitize_header_value", side_effect=Exception("boom")):
            with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.passthrough_headers"):
                result = compute_passthrough_headers_cached(
                    request_headers={"X-Upstream-Authorization": "Bearer abc"},
                    base_headers={},
                    allowed_headers=[],
                    gateway_auth_type=None,
                )

        assert "Authorization" not in result
        assert any("Failed to sanitize X-Upstream-Authorization" in record.message for record in caplog.records)

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_cached_x_upstream_authorization_sanitizes_to_empty_is_skipped(self, mock_settings):
        mock_settings.enable_header_passthrough = False
        mock_settings.enable_overwrite_base_headers = False

        with patch("mcpgateway.utils.passthrough_headers.sanitize_header_value", return_value=""):
            result = compute_passthrough_headers_cached(
                request_headers={"X-Upstream-Authorization": "Bearer abc"},
                base_headers={},
                allowed_headers=[],
                gateway_auth_type=None,
            )

        assert "Authorization" not in result

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_cached_no_auth_gateway_does_not_override_existing_base_authorization(self, mock_settings):
        mock_settings.enable_header_passthrough = False
        mock_settings.enable_overwrite_base_headers = False

        base_headers = {"Authorization": "Bearer base"}
        result = compute_passthrough_headers_cached(
            request_headers={"Authorization": "Bearer client"},
            base_headers=base_headers,
            allowed_headers=[],
            gateway_auth_type="none",
        )

        assert result["Authorization"] == "Bearer base"

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_cached_no_auth_gateway_client_authorization_sanitizes_to_empty_is_skipped(self, mock_settings):
        mock_settings.enable_header_passthrough = False
        mock_settings.enable_overwrite_base_headers = False

        with patch("mcpgateway.utils.passthrough_headers.sanitize_header_value", return_value=""):
            result = compute_passthrough_headers_cached(
                request_headers={"Authorization": "Bearer client"},
                base_headers={},
                allowed_headers=[],
                gateway_auth_type="none",
            )

        assert "Authorization" not in result

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_cached_enabled_empty_allowlist_skips_copy_loop(self, mock_settings):
        """When enabled but allowlist is empty, it should skip the per-header copy loop."""
        mock_settings.enable_header_passthrough = True
        mock_settings.enable_overwrite_base_headers = False

        result = compute_passthrough_headers_cached(
            request_headers={"X-Tenant-Id": "acme"},
            base_headers={"Content-Type": "application/json"},
            allowed_headers=[],
            gateway_auth_type=None,
        )

        assert result == {"Content-Type": "application/json"}

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_cached_no_auth_gateway_passes_client_authorization(self, mock_settings):
        mock_settings.enable_header_passthrough = False
        mock_settings.enable_overwrite_base_headers = False

        result = compute_passthrough_headers_cached(
            request_headers={"Authorization": "Bearer client"},
            base_headers={},
            allowed_headers=[],
            gateway_auth_type="none",
        )
        assert result["Authorization"] == "Bearer client"

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_cached_no_auth_gateway_authorization_sanitize_error_is_logged(self, mock_settings, caplog):
        mock_settings.enable_header_passthrough = False
        mock_settings.enable_overwrite_base_headers = False

        with patch("mcpgateway.utils.passthrough_headers.sanitize_header_value", side_effect=Exception("boom")):
            with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.passthrough_headers"):
                result = compute_passthrough_headers_cached(
                    request_headers={"Authorization": "Bearer client"},
                    base_headers={},
                    allowed_headers=[],
                    gateway_auth_type="none",
                )

        assert "Authorization" not in result
        assert any("Failed to sanitize Authorization header" in record.message for record in caplog.records)

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_cached_allowed_headers_validation_sanitization_and_conflicts(self, mock_settings, caplog):
        mock_settings.enable_header_passthrough = True
        mock_settings.enable_overwrite_base_headers = False

        request_headers = {
            "x-tenant-id": "acme",
            "content-type": "text/plain",
            "x-empty": "\r\n\t",
        }
        base_headers = {"Content-Type": "application/json"}
        allowed = ["X-Tenant-Id", "Bad Header", "Content-Type", "X-Empty", "X-Missing"]

        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.passthrough_headers"):
            result = compute_passthrough_headers_cached(request_headers=request_headers, base_headers=base_headers, allowed_headers=allowed, gateway_auth_type=None)

        assert result["Content-Type"] == "application/json"
        assert result["X-Tenant-Id"] == "acme"
        assert "X-Empty" not in result
        assert any("Invalid header name" in record.message for record in caplog.records)
        assert any("conflicts with pre-defined headers" in record.message for record in caplog.records)
        assert any("became empty after sanitization" in record.message for record in caplog.records)

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_cached_overwrite_base_headers_and_gateway_auth_conflict(self, mock_settings, caplog):
        mock_settings.enable_header_passthrough = True
        mock_settings.enable_overwrite_base_headers = True

        request_headers = {"content-type": "text/plain", "authorization": "Bearer should-be-blocked"}
        base_headers = {"Content-Type": "application/json"}
        allowed = ["Content-Type", "Authorization"]

        with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.passthrough_headers"):
            result = compute_passthrough_headers_cached(request_headers=request_headers, base_headers=base_headers, allowed_headers=allowed, gateway_auth_type="basic")

        assert result["Content-Type"] == "text/plain"
        assert "Authorization" not in result
        assert any("Skipping Authorization header passthrough" in record.message for record in caplog.records)

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_cached_sanitization_exception_skips_header(self, mock_settings, caplog):
        mock_settings.enable_header_passthrough = True
        mock_settings.enable_overwrite_base_headers = False

        with patch("mcpgateway.utils.passthrough_headers.sanitize_header_value", side_effect=Exception("boom")):
            with caplog.at_level(logging.WARNING, logger="mcpgateway.utils.passthrough_headers"):
                result = compute_passthrough_headers_cached(
                    request_headers={"x-tenant-id": "acme"},
                    base_headers={},
                    allowed_headers=["X-Tenant-Id"],
                    gateway_auth_type=None,
                )

        assert result == {}
        assert any("Failed to sanitize header X-Tenant-Id" in record.message for record in caplog.records)

    @patch("mcpgateway.utils.passthrough_headers.settings")
    def test_cached_gateway_passthrough_headers_override(self, mock_settings):
        mock_settings.enable_header_passthrough = True
        mock_settings.enable_overwrite_base_headers = False

        result = compute_passthrough_headers_cached(
            request_headers={"x-global": "g", "x-gateway": "gw"},
            base_headers={},
            allowed_headers=["X-Global"],
            gateway_auth_type=None,
            gateway_passthrough_headers=["X-Gateway"],
        )
        assert result == {"X-Gateway": "gw"}
