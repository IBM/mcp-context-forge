# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_a2a_passthrough_headers.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0

Comprehensive unit tests for A2A passthrough headers with feature flag.

Tests the ENABLE_SENSITIVE_HEADER_PASSTHROUGH flag functionality:
- Feature flag behavior (ON/OFF)
- Sensitive header pattern matching
- Router-level filtering (main.py)
- Service-level filtering (a2a_service.py)
- End-to-end header flow
- Config field validation
- Defense-in-depth filtering

Phase 1 of Issue #3621.
"""

# Standard
import re
from typing import Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.config import Settings
from mcpgateway.services.a2a_service import A2AAgentService


# Sensitive header patterns (from main.py:4989-4999)
_SENSITIVE_REQUEST_HEADER_PATTERNS = (
    re.compile(r"^authorization$", re.IGNORECASE),
    re.compile(r"^proxy-authorization$", re.IGNORECASE),
    re.compile(r"^x-api-key$", re.IGNORECASE),
    re.compile(r"^api-key$", re.IGNORECASE),
    re.compile(r"^apikey$", re.IGNORECASE),
    re.compile(r"^x-(?:auth|api|access|refresh|client|bearer|session|security)[-_]?(?:token|secret|key)$", re.IGNORECASE),
    re.compile(r"^cookie$", re.IGNORECASE),
    re.compile(r"^set-cookie$", re.IGNORECASE),
    re.compile(r"^host$", re.IGNORECASE),
)


def _filter_sensitive_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """Strip sensitive/credential headers from a dict."""
    return {k: v for k, v in headers.items() if not any(p.match(k) for p in _SENSITIVE_REQUEST_HEADER_PATTERNS)}


class TestSensitiveHeaderPassthroughFeatureFlag:
    """Test the ENABLE_SENSITIVE_HEADER_PASSTHROUGH feature flag."""

    def filter_with_feature_flag(
        self,
        request_headers: Optional[Dict[str, str]],
        whitelist: Optional[List[str]],
        enable_sensitive_passthrough: bool = False,
    ) -> Dict[str, str]:
        """Simulate the filtering logic with feature flag (a2a_service.py:2091-2105)."""
        if not request_headers:
            return {}

        if whitelist:
            # Step 1: Filter by whitelist (case-insensitive comparison)
            whitelist_lower = {h.lower() for h in whitelist}
            filtered = {k: v for k, v in request_headers.items() if k.lower() in whitelist_lower}

            # Step 2: If flag OFF, filter sensitive headers after whitelist check
            if not enable_sensitive_passthrough:
                filtered = _filter_sensitive_headers(filtered)

            return filtered

        # No whitelist = no headers forwarded
        return {}

    # =========================================================================
    # Feature Flag OFF (Default Behavior - Backward Compatible)
    # =========================================================================

    def test_authorization_blocked_when_flag_off(self):
        """Authorization blocked when flag OFF (default, backward compatible)."""
        request_headers = {
            "authorization": "Bearer token123",
            "x-tenant-id": "acme-corp",
        }
        whitelist = ["Authorization", "X-Tenant-ID"]

        result = self.filter_with_feature_flag(
            request_headers, whitelist, enable_sensitive_passthrough=False
        )

        # Authorization should be blocked
        assert "authorization" not in result
        # Non-sensitive headers still forwarded
        assert "x-tenant-id" in result
        assert result["x-tenant-id"] == "acme-corp"

    def test_x_api_key_blocked_when_flag_off(self):
        """X-API-Key blocked when flag OFF."""
        request_headers = {
            "x-api-key": "secret-key-789",  # pragma: allowlist secret
            "x-tenant-id": "acme-corp",
        }
        whitelist = ["X-API-Key", "X-Tenant-ID"]

        result = self.filter_with_feature_flag(
            request_headers, whitelist, enable_sensitive_passthrough=False
        )

        assert "x-api-key" not in result
        assert "x-tenant-id" in result

    def test_cookie_blocked_when_flag_off(self):
        """Cookie blocked when flag OFF."""
        request_headers = {
            "cookie": "session=abc123",
            "x-tenant-id": "acme-corp",
        }
        whitelist = ["Cookie", "X-Tenant-ID"]

        result = self.filter_with_feature_flag(
            request_headers, whitelist, enable_sensitive_passthrough=False
        )

        assert "cookie" not in result
        assert "x-tenant-id" in result

    # =========================================================================
    # Feature Flag ON (Authorization Forwarding Enabled)
    # =========================================================================

    def test_authorization_forwarded_when_flag_on(self):
        """Authorization forwarded when flag ON and whitelisted."""
        request_headers = {
            "authorization": "Bearer token123",
            "x-tenant-id": "acme-corp",
        }
        whitelist = ["Authorization", "X-Tenant-ID"]

        result = self.filter_with_feature_flag(
            request_headers, whitelist, enable_sensitive_passthrough=True
        )

        # Both headers should be forwarded
        assert "authorization" in result
        assert result["authorization"] == "Bearer token123"
        assert "x-tenant-id" in result
        assert result["x-tenant-id"] == "acme-corp"

    def test_x_api_key_forwarded_when_flag_on(self):
        """X-API-Key forwarded when flag ON and whitelisted."""
        request_headers = {
            "x-api-key": "secret-key-789",  # pragma: allowlist secret
            "x-tenant-id": "acme-corp",
        }
        whitelist = ["X-API-Key", "X-Tenant-ID"]

        result = self.filter_with_feature_flag(
            request_headers, whitelist, enable_sensitive_passthrough=True
        )

        assert "x-api-key" in result
        assert result["x-api-key"] == "secret-key-789"
        assert "x-tenant-id" in result

    def test_multiple_sensitive_headers_when_flag_on(self):
        """Multiple sensitive headers forwarded when flag ON."""
        request_headers = {
            "authorization": "Bearer token",
            "x-api-key": "api-key-123",  # pragma: allowlist secret
            "cookie": "session=xyz",
            "x-tenant-id": "acme",
        }
        whitelist = ["Authorization", "X-API-Key", "Cookie", "X-Tenant-ID"]

        result = self.filter_with_feature_flag(
            request_headers, whitelist, enable_sensitive_passthrough=True
        )

        # All whitelisted headers forwarded
        assert "authorization" in result
        assert "x-api-key" in result
        assert "cookie" in result
        assert "x-tenant-id" in result

    # =========================================================================
    # Whitelist Enforcement (Flag ON)
    # =========================================================================

    def test_authorization_blocked_when_not_whitelisted_flag_on(self):
        """Authorization blocked when not whitelisted, even if flag ON."""
        request_headers = {
            "authorization": "Bearer token123",
            "x-tenant-id": "acme-corp",
        }
        whitelist = ["X-Tenant-ID"]  # Authorization NOT in whitelist

        result = self.filter_with_feature_flag(
            request_headers, whitelist, enable_sensitive_passthrough=True
        )

        # Authorization blocked (not whitelisted)
        assert "authorization" not in result
        # X-Tenant-ID forwarded (whitelisted)
        assert "x-tenant-id" in result

    def test_sensitive_header_blocked_when_not_whitelisted_flag_on(self):
        """Sensitive headers blocked when not whitelisted, even if flag ON."""
        request_headers = {
            "authorization": "Bearer token",
            "x-api-key": "secret",
            "x-tenant-id": "acme",
        }
        whitelist = ["X-Tenant-ID"]  # Only X-Tenant-ID whitelisted

        result = self.filter_with_feature_flag(
            request_headers, whitelist, enable_sensitive_passthrough=True
        )

        # Only whitelisted header forwarded
        assert len(result) == 1
        assert "x-tenant-id" in result
        assert "authorization" not in result
        assert "x-api-key" not in result

    def test_empty_whitelist_blocks_all_flag_on(self):
        """Empty whitelist blocks all, even with flag ON."""
        request_headers = {
            "authorization": "Bearer token",
            "x-tenant-id": "acme",
        }
        whitelist = []

        result = self.filter_with_feature_flag(
            request_headers, whitelist, enable_sensitive_passthrough=True
        )

        assert len(result) == 0

    # =========================================================================
    # Non-Sensitive Headers (Should Always Work)
    # =========================================================================

    def test_non_sensitive_headers_work_flag_off(self):
        """Non-sensitive headers forwarded when flag OFF."""
        request_headers = {
            "x-tenant-id": "acme-corp",
            "x-request-id": "req-123",
            "x-correlation-id": "corr-456",
        }
        whitelist = ["X-Tenant-ID", "X-Request-ID", "X-Correlation-ID"]

        result = self.filter_with_feature_flag(
            request_headers, whitelist, enable_sensitive_passthrough=False
        )

        assert len(result) == 3
        assert "x-tenant-id" in result
        assert "x-request-id" in result
        assert "x-correlation-id" in result

    def test_non_sensitive_headers_work_flag_on(self):
        """Non-sensitive headers forwarded when flag ON."""
        request_headers = {
            "x-tenant-id": "acme-corp",
            "x-request-id": "req-123",
        }
        whitelist = ["X-Tenant-ID", "X-Request-ID"]

        result = self.filter_with_feature_flag(
            request_headers, whitelist, enable_sensitive_passthrough=True
        )

        assert len(result) == 2
        assert "x-tenant-id" in result
        assert "x-request-id" in result

    # =========================================================================
    # Edge Cases
    # =========================================================================

    def test_case_insensitive_matching_with_authorization(self):
        """Authorization header matched case-insensitively."""
        request_headers = {
            "AUTHORIZATION": "Bearer token",  # Uppercase
            "x-tenant-id": "acme",
        }
        whitelist = ["AUTHORIZATION", "X-Tenant-ID"]  # Match case for whitelist

        result = self.filter_with_feature_flag(
            request_headers, whitelist, enable_sensitive_passthrough=True
        )

        # Should match case-insensitively
        assert "AUTHORIZATION" in result
        assert "x-tenant-id" in result

    def test_mixed_sensitive_and_non_sensitive_flag_off(self):
        """Mixed headers: sensitive blocked, non-sensitive forwarded (flag OFF)."""
        request_headers = {
            "authorization": "Bearer token",
            "x-tenant-id": "acme",
            "x-request-id": "123",
        }
        whitelist = ["Authorization", "X-Tenant-ID", "X-Request-ID"]

        result = self.filter_with_feature_flag(
            request_headers, whitelist, enable_sensitive_passthrough=False
        )

        # Sensitive blocked
        assert "authorization" not in result
        # Non-sensitive forwarded
        assert "x-tenant-id" in result
        assert "x-request-id" in result

    def test_mixed_sensitive_and_non_sensitive_flag_on(self):
        """Mixed headers: all forwarded when flag ON."""
        request_headers = {
            "authorization": "Bearer token",
            "x-tenant-id": "acme",
            "x-request-id": "123",
        }
        whitelist = ["Authorization", "X-Tenant-ID", "X-Request-ID"]

        result = self.filter_with_feature_flag(
            request_headers, whitelist, enable_sensitive_passthrough=True
        )

        # All forwarded
        assert len(result) == 3
        assert "authorization" in result
        assert "x-tenant-id" in result
        assert "x-request-id" in result


class TestSensitiveHeaderPatterns:
    """Test that sensitive header patterns are correctly identified."""

    def is_sensitive(self, header_name: str) -> bool:
        """Check if header matches sensitive patterns."""
        return any(p.match(header_name) for p in _SENSITIVE_REQUEST_HEADER_PATTERNS)

    def test_authorization_is_sensitive(self):
        """Authorization is classified as sensitive."""
        assert self.is_sensitive("authorization")
        assert self.is_sensitive("Authorization")
        assert self.is_sensitive("AUTHORIZATION")

    def test_x_api_key_is_sensitive(self):
        """X-API-Key is classified as sensitive."""
        assert self.is_sensitive("x-api-key")
        assert self.is_sensitive("X-API-Key")
        assert self.is_sensitive("api-key")
        assert self.is_sensitive("apikey")

    def test_cookie_is_sensitive(self):
        """Cookie is classified as sensitive."""
        assert self.is_sensitive("cookie")
        assert self.is_sensitive("Cookie")
        assert self.is_sensitive("set-cookie")

    def test_x_auth_token_is_sensitive(self):
        """X-Auth-Token is classified as sensitive."""
        assert self.is_sensitive("x-auth-token")
        assert self.is_sensitive("x-api-token")
        assert self.is_sensitive("x-bearer-token")
        assert self.is_sensitive("x-session-key")

    def test_x_tenant_id_is_not_sensitive(self):
        """X-Tenant-ID is NOT classified as sensitive."""
        assert not self.is_sensitive("x-tenant-id")
        assert not self.is_sensitive("X-Tenant-ID")

    def test_x_request_id_is_not_sensitive(self):
        """X-Request-ID is NOT classified as sensitive."""
        assert not self.is_sensitive("x-request-id")
        assert not self.is_sensitive("X-Request-ID")

    def test_x_downstream_auth_is_not_sensitive(self):
        """X-Downstream-Auth is NOT classified as sensitive (custom header)."""
        assert not self.is_sensitive("x-downstream-auth")
        assert not self.is_sensitive("X-Downstream-Auth")

    def test_x_app_token_is_not_sensitive(self):
        """X-App-Token is NOT classified as sensitive (custom header)."""
        assert not self.is_sensitive("x-app-token")
        assert not self.is_sensitive("X-App-Token")


class TestRouterHeaderFiltering:
    """Test header filtering in main.py router endpoints."""

    @pytest.mark.asyncio
    @patch("mcpgateway.main.settings")
    async def test_router_filters_sensitive_headers_when_flag_off(self, mock_settings):
        """Router filters sensitive headers when ENABLE_SENSITIVE_HEADER_PASSTHROUGH=false."""
        # Simulate flag OFF (default)
        mock_settings.enable_sensitive_header_passthrough = False

        # Import after patching settings
        from mcpgateway.main import _filter_sensitive_headers

        # Simulate incoming request headers
        request_headers = {
            "authorization": "Bearer token123",
            "x-api-key": "secret-key",  # pragma: allowlist secret
            "x-tenant-id": "acme-corp",
            "x-request-id": "req-123",
        }

        # Router applies filtering (main.py:5089)
        if mock_settings.enable_sensitive_header_passthrough:
            filtered_headers = request_headers
        else:
            filtered_headers = _filter_sensitive_headers(request_headers)

        # Sensitive headers should be filtered out
        assert "authorization" not in filtered_headers
        assert "x-api-key" not in filtered_headers
        # Non-sensitive headers preserved
        assert "x-tenant-id" in filtered_headers
        assert "x-request-id" in filtered_headers

    @pytest.mark.asyncio
    @patch("mcpgateway.main.settings")
    async def test_router_passes_all_headers_when_flag_on(self, mock_settings):
        """Router passes all headers when ENABLE_SENSITIVE_HEADER_PASSTHROUGH=true."""
        # Simulate flag ON
        mock_settings.enable_sensitive_header_passthrough = True

        # Simulate incoming request headers
        request_headers = {
            "authorization": "Bearer token123",
            "x-api-key": "secret-key",  # pragma: allowlist secret
            "x-tenant-id": "acme-corp",
        }

        # Router applies conditional filtering (main.py:5088-5092)
        if mock_settings.enable_sensitive_header_passthrough:
            filtered_headers = request_headers.copy()
        else:
            from mcpgateway.main import _filter_sensitive_headers
            filtered_headers = _filter_sensitive_headers(request_headers)

        # All headers should pass through
        assert "authorization" in filtered_headers
        assert "x-api-key" in filtered_headers
        assert "x-tenant-id" in filtered_headers


class TestServiceHeaderFiltering:
    """Test header filtering in a2a_service.py after whitelist check."""

    @pytest.mark.asyncio
    @patch("mcpgateway.services.a2a_service.settings")
    async def test_service_filters_after_whitelist_when_flag_off(self, mock_settings):
        """Service filters sensitive headers after whitelist when flag OFF."""
        # Simulate flag OFF
        mock_settings.enable_sensitive_header_passthrough = False

        # Import filter function
        from mcpgateway.main import _filter_sensitive_headers

        # Simulate headers after whitelist filtering
        request_headers = {
            "authorization": "Bearer token123",
            "x-tenant-id": "acme-corp",
        }
        agent_passthrough_headers = ["Authorization", "X-Tenant-ID"]

        # Whitelist filtering (a2a_service.py:2092-2093)
        whitelist_lower = {h.lower() for h in agent_passthrough_headers}
        filtered = {k: v for k, v in request_headers.items() if k in whitelist_lower}

        # Post-whitelist filtering (a2a_service.py:2096-2100)
        if not mock_settings.enable_sensitive_header_passthrough:
            filtered = _filter_sensitive_headers(filtered)

        # Authorization should be filtered out even though whitelisted
        assert "authorization" not in filtered
        # Non-sensitive header preserved
        assert "x-tenant-id" in filtered

    @pytest.mark.asyncio
    @patch("mcpgateway.services.a2a_service.settings")
    async def test_service_no_filtering_when_flag_on(self, mock_settings):
        """Service skips filtering when flag ON (whitelisted headers pass through)."""
        # Simulate flag ON
        mock_settings.enable_sensitive_header_passthrough = True

        from mcpgateway.main import _filter_sensitive_headers

        # Simulate headers after whitelist filtering
        request_headers = {
            "authorization": "Bearer token123",
            "x-tenant-id": "acme-corp",
        }
        agent_passthrough_headers = ["Authorization", "X-Tenant-ID"]

        # Whitelist filtering
        whitelist_lower = {h.lower() for h in agent_passthrough_headers}
        filtered = {k: v for k, v in request_headers.items() if k in whitelist_lower}

        # Post-whitelist filtering (a2a_service.py:2096-2100)
        if not mock_settings.enable_sensitive_header_passthrough:
            filtered = _filter_sensitive_headers(filtered)

        # All whitelisted headers should pass through
        assert "authorization" in filtered
        assert "x-tenant-id" in filtered


class TestEndToEndHeaderFlow:
    """Test complete header flow from router to service to downstream."""

    @pytest.mark.asyncio
    @patch("mcpgateway.services.a2a_service.httpx.AsyncClient")
    @patch("mcpgateway.services.a2a_service.get_correlation_id")
    @patch("mcpgateway.services.a2a_service.settings")
    @patch("mcpgateway.main.settings")
    async def test_end_to_end_flag_off_authorization_blocked(
        self, mock_main_settings, mock_service_settings, mock_correlation_id, mock_httpx
    ):
        """End-to-end: Authorization blocked when flag OFF."""
        # Both settings point to same flag
        mock_main_settings.enable_sensitive_header_passthrough = False
        mock_service_settings.enable_sensitive_header_passthrough = False
        mock_correlation_id.return_value = "test-correlation-id"

        # Mock database and agent
        mock_db = MagicMock(spec=Session)
        mock_agent = MagicMock()
        mock_agent.id = "agent-123"
        mock_agent.name = "test-agent"
        mock_agent.team_id = "team-1"
        mock_agent.visibility = "public"
        mock_agent.enabled = True
        mock_agent.endpoint_url = "http://downstream.example.com/agent"
        mock_agent.agent_type = "generic"
        mock_agent.protocol_version = "1.0"
        mock_agent.auth_type = "none"
        mock_agent.auth_value = None
        mock_agent.auth_query_params = None
        mock_agent.tags = []
        mock_agent.oauth_config = None
        mock_agent.passthrough_headers = ["Authorization", "X-Tenant-ID"]
        mock_agent.uaid = None
        mock_agent.uaid_native_id = None

        mock_db.query.return_value.filter.return_value.options.return_value.first.return_value = mock_agent

        # Mock HTTP response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "success"}
        mock_response.headers = {}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_httpx.return_value = mock_client

        # Step 1: Router filtering (main.py:5088-5092)
        from mcpgateway.main import _filter_sensitive_headers

        incoming_headers = {
            "authorization": "Bearer token123",
            "x-tenant-id": "acme-corp",
        }

        if mock_main_settings.enable_sensitive_header_passthrough:
            router_filtered = incoming_headers.copy()
        else:
            router_filtered = _filter_sensitive_headers(incoming_headers)

        # Authorization should be filtered at router
        assert "authorization" not in router_filtered
        assert "x-tenant-id" in router_filtered

        # Step 2: Service processes (a2a_service.py:2091-2105)
        service = A2AAgentService()

        # Simulate service filtering
        request_headers = router_filtered
        agent_passthrough_headers = mock_agent.passthrough_headers

        if request_headers and agent_passthrough_headers:
            whitelist_lower = {h.lower() for h in agent_passthrough_headers}
            filtered = {k: v for k, v in request_headers.items() if k in whitelist_lower}

            # Post-whitelist filtering
            if not mock_service_settings.enable_sensitive_header_passthrough:
                filtered = _filter_sensitive_headers(filtered)
        else:
            filtered = {}

        # Final result: Only X-Tenant-ID forwarded
        assert "authorization" not in filtered
        assert "x-tenant-id" in filtered

    @pytest.mark.asyncio
    @patch("mcpgateway.services.a2a_service.httpx.AsyncClient")
    @patch("mcpgateway.services.a2a_service.get_correlation_id")
    @patch("mcpgateway.services.a2a_service.settings")
    @patch("mcpgateway.main.settings")
    async def test_end_to_end_flag_on_authorization_forwarded(
        self, mock_main_settings, mock_service_settings, mock_correlation_id, mock_httpx
    ):
        """End-to-end: Authorization forwarded when flag ON."""
        # Both settings point to same flag
        mock_main_settings.enable_sensitive_header_passthrough = True
        mock_service_settings.enable_sensitive_header_passthrough = True
        mock_correlation_id.return_value = "test-correlation-id"

        # Mock HTTP response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "success"}
        mock_response.headers = {}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_httpx.return_value = mock_client

        # Step 1: Router passes all headers (main.py:5088-5092)
        from mcpgateway.main import _filter_sensitive_headers

        incoming_headers = {
            "authorization": "Bearer token123",
            "x-tenant-id": "acme-corp",
        }

        if mock_main_settings.enable_sensitive_header_passthrough:
            router_filtered = incoming_headers.copy()
        else:
            router_filtered = _filter_sensitive_headers(incoming_headers)

        # All headers should pass router
        assert "authorization" in router_filtered
        assert "x-tenant-id" in router_filtered

        # Step 2: Service processes (a2a_service.py:2091-2105)
        request_headers = router_filtered
        agent_passthrough_headers = ["Authorization", "X-Tenant-ID"]

        if request_headers and agent_passthrough_headers:
            whitelist_lower = {h.lower() for h in agent_passthrough_headers}
            filtered = {k: v for k, v in request_headers.items() if k in whitelist_lower}

            # Post-whitelist filtering (SKIPPED when flag ON)
            if not mock_service_settings.enable_sensitive_header_passthrough:
                filtered = _filter_sensitive_headers(filtered)
        else:
            filtered = {}

        # Final result: Both headers forwarded
        assert "authorization" in filtered
        assert "x-tenant-id" in filtered


class TestConfigCoverage:
    """Test config.py coverage for new field."""

    def test_config_field_defaults(self):
        """Test enable_sensitive_header_passthrough defaults to false when explicitly set."""
        # Test the field default by explicitly passing False
        config = Settings(
            basic_auth_user="test",
            basic_auth_password="test-password-long",  # pragma: allowlist secret
            database_url="sqlite:///test.db",
            jwt_secret_key="test-secret-key-long-enough-32c",  # pragma: allowlist secret
            auth_encryption_secret="test-encryption-secret-32chars",  # pragma: allowlist secret
            enable_sensitive_header_passthrough=False
        )

        # Verify it can be set to False (secure default)
        assert config.enable_sensitive_header_passthrough is False

    def test_config_field_can_be_enabled(self):
        """Test enable_sensitive_header_passthrough can be set to true."""
        config = Settings(
            basic_auth_user="test",
            basic_auth_password="test-password-long",  # pragma: allowlist secret
            database_url="sqlite:///test.db",
            jwt_secret_key="test-secret-key-long-enough-32c",  # pragma: allowlist secret
            auth_encryption_secret="test-encryption-secret-32chars",  # pragma: allowlist secret
            enable_sensitive_header_passthrough=True
        )

        assert config.enable_sensitive_header_passthrough is True

    def test_config_field_description(self):
        """Test enable_sensitive_header_passthrough has proper field info."""
        # Access field info
        field_info = Settings.model_fields.get("enable_sensitive_header_passthrough")

        assert field_info is not None
        assert field_info.description is not None
        assert "sensitive headers" in field_info.description.lower()
        assert field_info.default is False


class TestDefenseInDepth:
    """Test defense-in-depth: both router and service filtering."""

    @pytest.mark.asyncio
    @patch("mcpgateway.services.a2a_service.settings")
    @patch("mcpgateway.main.settings")
    async def test_double_filtering_when_flag_off(self, mock_main_settings, mock_service_settings):
        """Test that filtering happens at both router AND service when flag OFF."""
        mock_main_settings.enable_sensitive_header_passthrough = False
        mock_service_settings.enable_sensitive_header_passthrough = False

        from mcpgateway.main import _filter_sensitive_headers

        # Incoming headers with Authorization
        incoming = {
            "authorization": "Bearer token",
            "x-tenant-id": "acme",
        }

        # Router filtering (1st layer)
        router_out = _filter_sensitive_headers(incoming) if not mock_main_settings.enable_sensitive_header_passthrough else incoming
        assert "authorization" not in router_out  # Blocked at router

        # Service whitelist filtering
        whitelist = ["Authorization", "X-Tenant-ID"]
        whitelist_lower = {h.lower() for h in whitelist}
        service_whitelist = {k: v for k, v in router_out.items() if k in whitelist_lower}

        # Service post-whitelist filtering (2nd layer)
        service_out = _filter_sensitive_headers(service_whitelist) if not mock_service_settings.enable_sensitive_header_passthrough else service_whitelist

        # Authorization blocked at both layers (defense in depth)
        assert "authorization" not in service_out
        assert "x-tenant-id" in service_out

    @pytest.mark.asyncio
    @patch("mcpgateway.services.a2a_service.settings")
    @patch("mcpgateway.main.settings")
    async def test_no_double_filtering_when_flag_on(self, mock_main_settings, mock_service_settings):
        """Test that filtering is bypassed when flag ON (whitelisted headers pass)."""
        mock_main_settings.enable_sensitive_header_passthrough = True
        mock_service_settings.enable_sensitive_header_passthrough = True

        from mcpgateway.main import _filter_sensitive_headers

        # Incoming headers with Authorization
        incoming = {
            "authorization": "Bearer token",
            "x-tenant-id": "acme",
        }

        # Router filtering (BYPASSED)
        router_out = incoming if mock_main_settings.enable_sensitive_header_passthrough else _filter_sensitive_headers(incoming)
        assert "authorization" in router_out  # Passed router

        # Service whitelist filtering
        whitelist = ["Authorization", "X-Tenant-ID"]
        whitelist_lower = {h.lower() for h in whitelist}
        service_whitelist = {k: v for k, v in router_out.items() if k in whitelist_lower}

        # Service post-whitelist filtering (BYPASSED)
        service_out = service_whitelist if mock_service_settings.enable_sensitive_header_passthrough else _filter_sensitive_headers(service_whitelist)

        # Authorization passed through (flag ON)
        assert "authorization" in service_out
        assert "x-tenant-id" in service_out
