"""
Unit tests for UAID security features in A2AAgentService.

Tests cover:
- Fail-closed domain allowlist enforcement
- UAID-based allowlist validation
- Cross-gateway routing security gates
"""

import pytest
from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentService


class TestFailClosedDomainAllowlist:
    """Tests for fail-closed domain allowlist enforcement in _invoke_remote_agent."""

    @pytest.fixture
    def service(self):
        """Create A2AAgentService instance for testing."""
        return A2AAgentService()

    async def test_empty_allowlist_blocks_routing(self, service, monkeypatch):
        """
        Test that routing is blocked when allowlist is empty (fail-closed).

        Given: A remote routing request with empty domain allowlist
        When: _invoke_remote_agent is called
        Then: Should raise A2AAgentError with fail-closed message
        """
        # Arrange - set empty allowlist
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", [])

        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=remote.example.com"

        # Act & Assert - should raise fail-closed error
        with pytest.raises(A2AAgentError, match="UAID_ALLOWED_DOMAINS is empty"):
            await service._invoke_remote_agent(
                uaid=uaid,
                parameters={"test": "data"},
                interaction_type="request",
            )

    async def test_none_allowlist_blocks_routing(self, service, monkeypatch):
        """
        Test that routing is blocked when allowlist is None (fail-closed).

        Given: A remote routing request with None domain allowlist
        When: _invoke_remote_agent is called
        Then: Should raise A2AAgentError with fail-closed message
        """
        # Arrange - set None allowlist
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", None)

        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=remote.example.com"

        # Act & Assert - should raise fail-closed error
        with pytest.raises(A2AAgentError, match="UAID_ALLOWED_DOMAINS is empty"):
            await service._invoke_remote_agent(
                uaid=uaid,
                parameters={"test": "data"},
                interaction_type="request",
            )

    async def test_populated_allowlist_proceeds_to_validation(self, service, monkeypatch):
        """
        Test that routing proceeds to domain validation when allowlist is populated.

        Given: A remote routing request with populated domain allowlist
        When: _invoke_remote_agent is called
        Then: Should pass fail-closed gate and proceed to domain validation logic
        """
        # Third-Party
        import httpx

        # Arrange - set populated allowlist
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])

        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=remote.example.com"

        # Mock httpx.AsyncClient to avoid actual HTTP call
        async def mock_post(*args, **kwargs):
            # First-Party
            from unittest.mock import MagicMock

            response = MagicMock()
            response.status_code = 200
            response.json.return_value = {"result": "success"}
            return response

        monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

        # Act - should not raise fail-closed error
        # (may raise different error due to domain validation or other logic)
        try:
            result = await service._invoke_remote_agent(
                uaid=uaid,
                parameters={"test": "data"},
                interaction_type="request",
            )
            # If we get here, fail-closed gate was passed
            assert True
        except A2AAgentError as e:
            # If error raised, ensure it's NOT the fail-closed error
            assert "UAID_ALLOWED_DOMAINS is empty" not in str(e)
