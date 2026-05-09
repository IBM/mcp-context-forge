"""
Unit tests for IPv6 edge cases in UAID domain validation.

Tests cover:
- IPv6 with port handling ([::1]:8080)
- IPv6 localhost blocking
- Malformed IPv6 graceful failures
"""

import pytest
from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentService


class TestIPv6EdgeCases:
    """Tests for IPv6 address handling in domain validation."""

    @pytest.fixture
    def service(self):
        """Create A2AAgentService instance for testing."""
        return A2AAgentService()

    async def test_ipv6_with_port_validates_correctly(self, service, monkeypatch):
        """
        Test that IPv6 addresses with ports are parsed correctly.

        Given: UAID with IPv6 address [::1]:8080 in allowlist
        When: Domain validation occurs
        Then: Should extract ::1 and validate against allowlist
        """
        # Arrange - allowlist contains IPv6 without brackets
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["::1"])
        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=[::1]:8080"

        async def mock_post(*args, **kwargs):
            # First-Party
            from unittest.mock import MagicMock

            response = MagicMock()
            response.status_code = 200
            response.json.return_value = {"result": "success"}
            return response

        monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

        # Act - should succeed
        result = await service._invoke_remote_agent(
            uaid=uaid,
            parameters={"test": "data"},
            interaction_type="request",
        )

        # Assert
        assert result == {"result": "success"}

    async def test_ipv6_localhost_blocked(self, service, monkeypatch):
        """
        Test that IPv6 localhost (::1) is blocked even when in URL format.

        Given: UAID with IPv6 loopback address
        When: Domain validation occurs with empty allowlist
        Then: Should be blocked by fail-closed validation
        """
        # Arrange - empty allowlist (fail-closed)
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", [])
        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=[::1]:8080"

        # Act & Assert - should raise fail-closed error
        with pytest.raises(A2AAgentError, match="UAID_ALLOWED_DOMAINS is empty"):
            await service._invoke_remote_agent(
                uaid=uaid,
                parameters={"test": "data"},
                interaction_type="request",
            )

    async def test_malformed_ipv6_fails_gracefully(self, service, monkeypatch):
        """
        Test that malformed IPv6 addresses fail validation gracefully.

        Given: UAID with malformed IPv6 (missing closing bracket)
        When: Domain validation occurs
        Then: Should fail validation without crashing
        """
        # Arrange
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=[::1:8080"  # Missing ]

        # Act & Assert - should raise validation error (not crash)
        # Error message may be "invalid hostname format" or "not in UAID_ALLOWED_DOMAINS" depending on parsing path
        with pytest.raises(A2AAgentError, match="(invalid hostname format|not in UAID_ALLOWED_DOMAINS)"):
            await service._invoke_remote_agent(
                uaid=uaid,
                parameters={"test": "data"},
                interaction_type="request",
            )

    async def test_ipv6_with_subdomain_matching(self, service, monkeypatch):
        """
        Test that IPv6 addresses don't incorrectly match domain allowlists.

        Given: Allowlist contains domain "example.com"
        When: UAID contains IPv6 address
        Then: Should NOT match domain allowlist (IPv6 != domain)
        """
        # Arrange
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=[2001:db8::1]:8080"

        # Act & Assert - IPv6 should not match domain allowlist
        with pytest.raises(A2AAgentError, match="not in UAID_ALLOWED_DOMAINS"):
            await service._invoke_remote_agent(
                uaid=uaid,
                parameters={"test": "data"},
                interaction_type="request",
            )

    async def test_ipv6_expanded_form(self, service, monkeypatch):
        """
        Test that expanded IPv6 addresses validate correctly.

        Given: UAID with expanded IPv6 (2001:0db8:0000:0000:0000:0000:0000:0001)
        When: Domain validation occurs
        Then: Should parse and validate correctly
        """
        # Arrange - allowlist contains the expanded form
        monkeypatch.setattr(
            "mcpgateway.config.settings.uaid_allowed_domains",
            ["2001:0db8:0000:0000:0000:0000:0000:0001"]
        )
        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=[2001:0db8:0000:0000:0000:0000:0000:0001]:8080"

        async def mock_post(*args, **kwargs):
            # First-Party
            from unittest.mock import MagicMock

            response = MagicMock()
            response.status_code = 200
            response.json.return_value = {"result": "success"}
            return response

        monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

        # Act - should succeed
        result = await service._invoke_remote_agent(
            uaid=uaid,
            parameters={"test": "data"},
            interaction_type="request",
        )

        # Assert
        assert result == {"result": "success"}

    async def test_ipv6_without_brackets_in_allowlist(self, service, monkeypatch):
        """
        Test that IPv6 addresses work when allowlist contains address without brackets.

        Given: Allowlist contains "::1" (no brackets)
        When: UAID contains "[::1]:8080" (with brackets and port)
        Then: Should extract ::1 and match allowlist
        """
        # Arrange
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["::1"])
        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=[::1]:8080"

        async def mock_post(*args, **kwargs):
            # First-Party
            from unittest.mock import MagicMock

            response = MagicMock()
            response.status_code = 200
            response.json.return_value = {"result": "success"}
            return response

        monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

        # Act - should succeed
        result = await service._invoke_remote_agent(
            uaid=uaid,
            parameters={"test": "data"},
            interaction_type="request",
        )

        # Assert
        assert result == {"result": "success"}
