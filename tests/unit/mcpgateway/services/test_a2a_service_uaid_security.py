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


class TestUAIDDomainAllowlistValidation:
    """Tests for UAID domain allowlist validation logic."""

    @pytest.fixture
    def service(self):
        """Create A2AAgentService instance for testing."""
        return A2AAgentService()

    async def test_matching_domain_allows_routing(self, service, monkeypatch):
        """
        Test that routing is allowed when UAID domain matches allowlist entry.

        Given: A UAID with domain in allowlist
        When: _invoke_remote_agent is called
        Then: Should proceed with HTTP call (not raise domain validation error)
        """
        # Third-Party
        import httpx

        # Arrange
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=agent.example.com"

        # Mock httpx response
        async def mock_post(*args, **kwargs):
            # First-Party
            from unittest.mock import MagicMock

            response = MagicMock()
            response.status_code = 200
            response.json.return_value = {"result": "success"}
            return response

        monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

        # Act
        result = await service._invoke_remote_agent(
            uaid=uaid,
            parameters={"test": "data"},
            interaction_type="request",
        )

        # Assert - should not raise domain validation error
        assert result == {"result": "success"}

    async def test_non_matching_domain_blocks_routing(self, service, monkeypatch):
        """
        Test that routing is blocked when UAID domain not in allowlist.

        Given: A UAID with domain not in allowlist
        When: _invoke_remote_agent is called
        Then: Should raise A2AAgentError with domain validation message
        """
        # Arrange
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["allowed.com"])
        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=blocked.example.com"

        # Act & Assert
        with pytest.raises(A2AAgentError, match="not in UAID_ALLOWED_DOMAINS"):
            await service._invoke_remote_agent(
                uaid=uaid,
                parameters={"test": "data"},
                interaction_type="request",
            )

    async def test_subdomain_matching_logic(self, service, monkeypatch):
        """
        Test that subdomain matching works correctly in allowlist validation.

        Given: Allowlist contains parent domain
        When: UAID contains subdomain
        Then: Should allow routing (subdomain matches parent domain)
        """
        # Third-Party
        import httpx

        # Arrange
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=sub.example.com"

        # Mock httpx response
        async def mock_post(*args, **kwargs):
            # First-Party
            from unittest.mock import MagicMock

            response = MagicMock()
            response.status_code = 200
            response.json.return_value = {"result": "success"}
            return response

        monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

        # Act
        result = await service._invoke_remote_agent(
            uaid=uaid,
            parameters={"test": "data"},
            interaction_type="request",
        )

        # Assert - should not raise domain validation error
        assert result == {"result": "success"}



class TestUAIDBearerTokenForwarding:
    """Tests for bearer token forwarding in cross-gateway A2A calls."""

    @pytest.fixture
    def service(self):
        """Create A2AAgentService instance for testing."""
        return A2AAgentService()

    async def test_bearer_token_forwarded_in_headers(self, service, monkeypatch):
        """
        Test that bearer token is forwarded via Authorization header.

        Given: A bearer token is provided
        When: _invoke_remote_agent is called
        Then: Should include Authorization: Bearer {token} in HTTP headers
        """
        # Third-Party
        import httpx

        # Arrange
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=agent.example.com"
        test_token = "test-bearer-token-12345"

        captured_headers = {}

        async def mock_post(*args, **kwargs):
            # First-Party
            from unittest.mock import MagicMock

            # Capture headers for assertion
            captured_headers.update(kwargs.get("headers", {}))
            response = MagicMock()
            response.status_code = 200
            response.json.return_value = {"result": "success"}
            return response

        monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

        # Act
        await service._invoke_remote_agent(
            uaid=uaid,
            parameters={"test": "data"},
            interaction_type="request",
            bearer_token=test_token,
        )

        # Assert
        assert "Authorization" in captured_headers
        assert captured_headers["Authorization"] == f"Bearer {test_token}"

    async def test_audit_headers_included(self, service, monkeypatch):
        """
        Test that audit headers are included for tracing cross-gateway calls.

        Given: A bearer token is provided
        When: _invoke_remote_agent is called
        Then: Should include X-Contextforge-Source-Gateway and X-Contextforge-Source-User headers
        """
        # Third-Party
        import httpx

        # Arrange
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=agent.example.com"
        test_token = "test-bearer-token-12345"

        captured_headers = {}

        async def mock_post(*args, **kwargs):
            # First-Party
            from unittest.mock import MagicMock

            captured_headers.update(kwargs.get("headers", {}))
            response = MagicMock()
            response.status_code = 200
            response.json.return_value = {"result": "success"}
            return response

        monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

        # Act
        await service._invoke_remote_agent(
            uaid=uaid,
            parameters={"test": "data"},
            interaction_type="request",
            bearer_token=test_token,
        )

        # Assert
        assert "X-Contextforge-Source-Gateway" in captured_headers
        # Gateway ID defaults to "unknown" if not configured
        assert captured_headers["X-Contextforge-Source-Gateway"] == "unknown"
        assert "X-Contextforge-Source-User" in captured_headers
        # Token value should be in Source-User header for audit trail
        assert test_token in captured_headers["X-Contextforge-Source-User"]

    async def test_no_token_proceeds_without_auth_header(self, service, monkeypatch):
        """
        Test that call proceeds without Authorization header when no token provided.

        Given: No bearer token is provided (None)
        When: _invoke_remote_agent is called
        Then: Should proceed with HTTP call but without Authorization header
        """
        # Third-Party
        import httpx

        # Arrange
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=agent.example.com"

        captured_headers = {}

        async def mock_post(*args, **kwargs):
            # First-Party
            from unittest.mock import MagicMock

            captured_headers.update(kwargs.get("headers", {}))
            response = MagicMock()
            response.status_code = 200
            response.json.return_value = {"result": "success"}
            return response

        monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

        # Act
        result = await service._invoke_remote_agent(
            uaid=uaid,
            parameters={"test": "data"},
            interaction_type="request",
            bearer_token=None,
        )

        # Assert
        assert "Authorization" not in captured_headers
        assert result == {"result": "success"}

    async def test_warning_logged_when_no_token(self, service, monkeypatch, caplog):
        """
        Test that a warning is logged when no bearer token is provided.

        Given: No bearer token is provided
        When: _invoke_remote_agent is called
        Then: Should log warning about unauthenticated request
        """
        # Third-Party
        import httpx
        import logging

        # Arrange
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=agent.example.com"

        async def mock_post(*args, **kwargs):
            # First-Party
            from unittest.mock import MagicMock

            response = MagicMock()
            response.status_code = 200
            response.json.return_value = {"result": "success"}
            return response

        monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

        # Act
        with caplog.at_level(logging.WARNING):
            await service._invoke_remote_agent(
                uaid=uaid,
                parameters={"test": "data"},
                interaction_type="request",
                bearer_token=None,
            )

        # Assert
        assert any("Cross-gateway call without bearer token" in record.message for record in caplog.records)
        assert any("unauthenticated request" in record.message for record in caplog.records)
