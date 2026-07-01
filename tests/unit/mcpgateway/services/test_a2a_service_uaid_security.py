# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_a2a_service_uaid_security.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for UAID security features in A2AAgentService.

Tests cover:
- Fail-closed domain allowlist enforcement
- UAID-based allowlist validation
- Cross-gateway routing security gates
"""

import pytest
from mcpgateway.services.a2a_service import A2AAgentError, A2AAgentService


@pytest.fixture(autouse=True)
def disable_allow_all_domains(monkeypatch):
    """Keep UAID security tests deterministic regardless of env."""
    monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)


def _make_test_jwt() -> str:
    """Return a syntactically valid JWT for tests that expect token forwarding."""
    # Standard
    import base64

    return (
        base64.urlsafe_b64encode(b'{"alg":"HS256"}').decode().rstrip("=")
        + "."
        + base64.urlsafe_b64encode(b'{"sub":"user"}').decode().rstrip("=")
        + "."
        + base64.urlsafe_b64encode(b"signature").decode().rstrip("=")
    )


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
        test_token = _make_test_jwt()

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

        Given: A bearer token and user_email are provided
        When: _invoke_remote_agent is called
        Then: Should include X-Contextforge-Source-Gateway and X-Contextforge-Source-User headers
        """
        # Third-Party
        import httpx

        # Arrange
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=agent.example.com"
        test_token = _make_test_jwt()
        test_email = "user@example.com"

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
            user_email=test_email,
        )

        # Assert
        assert "X-Contextforge-Source-Gateway" in captured_headers
        # Gateway ID defaults to "unknown" if not configured
        assert captured_headers["X-Contextforge-Source-Gateway"] == "unknown"
        assert "X-Contextforge-Source-User" in captured_headers
        # SECURITY: User email should be in Source-User header, NOT the bearer token
        assert captured_headers["X-Contextforge-Source-User"] == test_email

    async def test_bearer_token_not_leaked_in_audit_header(self, service, monkeypatch):
        """
        SECURITY TEST: Verify bearer token is NOT leaked in X-Contextforge-Source-User header.

        Given: A bearer token and user_email are provided
        When: _invoke_remote_agent is called
        Then: X-Contextforge-Source-User should contain user_email, NOT the bearer token
        Rationale: Prevents credential leakage in logs/proxies that may capture headers
        """
        # Third-Party
        import httpx

        # Arrange
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=agent.example.com"
        test_token = _make_test_jwt()
        test_email = "user@example.com"

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
            user_email=test_email,
        )

        # Assert - CRITICAL SECURITY CHECK
        # The bearer token must ONLY appear in the Authorization header
        assert captured_headers["Authorization"] == f"Bearer {test_token}"

        # The X-Contextforge-Source-User header must contain the email, NOT the token
        assert "X-Contextforge-Source-User" in captured_headers
        source_user = captured_headers["X-Contextforge-Source-User"]
        assert source_user == test_email, f"Expected email '{test_email}', got '{source_user}'"

        # Explicitly verify token is NOT in the audit header
        assert test_token not in source_user, "SECURITY VIOLATION: Bearer token leaked in X-Contextforge-Source-User header!"

        # Verify token doesn't appear in ANY non-Authorization header
        for header_name, header_value in captured_headers.items():
            if header_name != "Authorization":
                assert test_token not in str(header_value), f"SECURITY VIOLATION: Token found in {header_name} header!"

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

    async def test_bearer_token_not_forwarded_when_disabled(self, service, monkeypatch, caplog):
        """
        DENY-PATH TEST: Verify bearer token is NOT forwarded when UAID_FORWARD_AUTH=false.

        Given: UAID_FORWARD_AUTH is set to false and a bearer token is provided
        When: _invoke_remote_agent is called
        Then: Should NOT include Authorization header and should log INFO message
        Rationale: Feature flag test per CLAUDE.md security invariants - deny-path regression test
        """
        # Third-Party
        import httpx
        import logging

        # Arrange
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_forward_auth", False)
        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=agent.example.com"
        test_token = _make_test_jwt()

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
        with caplog.at_level(logging.INFO):
            result = await service._invoke_remote_agent(
                uaid=uaid,
                parameters={"test": "data"},
                interaction_type="request",
                bearer_token=test_token,
            )

        # Assert - Feature disabled deny-path checks
        assert "Authorization" not in captured_headers, "SECURITY VIOLATION: Bearer token forwarded when UAID_FORWARD_AUTH=false!"
        assert result == {"result": "success"}

        # Verify INFO log message about disabled forwarding
        assert any("UAID_FORWARD_AUTH disabled" in record.message for record in caplog.records)
        assert any("not forwarding bearer token" in record.message for record in caplog.records)


class TestAuthenticationErrorHandling:
    """Tests for authentication error handling in cross-gateway calls."""

    @pytest.fixture
    def service(self):
        """Create A2AAgentService instance for testing."""
        return A2AAgentService()

    async def test_401_unauthorized_error_handling(self, service, monkeypatch):
        """
        Test that 401 errors are handled with clear authentication failure message.

        Given: Remote gateway returns 401 Unauthorized
        When: _invoke_remote_agent is called
        Then: Should raise A2AAgentError with message about JWT trust
        """
        # Third-Party
        import httpx

        # Arrange
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=agent.example.com"

        # Mock httpx response with 401
        async def mock_post(*args, **kwargs):
            # First-Party
            from unittest.mock import MagicMock

            response = MagicMock()
            response.status_code = 401
            response.text = "Unauthorized"
            response.content = b"Unauthorized"
            return response

        monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

        # Act & Assert
        with pytest.raises(
            A2AAgentError,
            match="Remote gateway rejected authentication.*Ensure both gateways trust the same JWT signing key",
        ):
            await service._invoke_remote_agent(
                uaid=uaid,
                parameters={"test": "data"},
                interaction_type="request",
                bearer_token=_make_test_jwt(),
            )

    async def test_403_forbidden_error_handling(self, service, monkeypatch):
        """
        Test that 403 errors are handled with clear authorization failure message.

        Given: Remote gateway returns 403 Forbidden
        When: _invoke_remote_agent is called
        Then: Should raise A2AAgentError with message about insufficient permissions
        """
        # Third-Party
        import httpx

        # Arrange
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=agent.example.com"

        # Mock httpx response with 403
        async def mock_post(*args, **kwargs):
            # First-Party
            from unittest.mock import MagicMock

            response = MagicMock()
            response.status_code = 403
            response.text = "Forbidden"
            response.content = b"Forbidden"
            return response

        monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

        # Act & Assert
        with pytest.raises(
            A2AAgentError,
            match="Remote gateway rejected authorization.*Verify token has required team memberships or roles",
        ):
            await service._invoke_remote_agent(
                uaid=uaid,
                parameters={"test": "data"},
                interaction_type="request",
                bearer_token=_make_test_jwt(),
            )


class TestBearerTokenForwardingGracefulDegradation:
    """Tests for bearer token forwarding graceful degradation."""

    @pytest.fixture
    def service(self):
        """Create A2AAgentService instance for testing."""
        return A2AAgentService()

    async def test_cross_gateway_call_without_bearer_token_proceeds_unauthenticated(self, service, monkeypatch, caplog):
        """
        Test that cross-gateway calls proceed without bearer token when not available.

        Given: A cross-gateway UAID call with no bearer_token provided
        When: _invoke_remote_agent is called without bearer_token parameter
        Then: Should proceed with HTTP call, log warning, and not raise exception
        """
        # First-Party
        from unittest.mock import AsyncMock, MagicMock
        import logging

        # Arrange
        monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_allowed_domains", ["example.com"])
        monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_forward_auth", True)

        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=agent.example.com"

        # Mock HTTP client response
        captured_headers = {}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "success"}

        async def mock_post(*args, **kwargs):
            # Capture headers to verify Authorization is not present
            captured_headers.update(kwargs.get("headers", {}))
            return mock_response

        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=mock_post)

        async def mock_get_http_client():
            return mock_client

        monkeypatch.setattr("mcpgateway.services.http_client_service.get_http_client", mock_get_http_client)

        # Act - call without bearer_token (simulates auth middleware failure)
        with caplog.at_level(logging.WARNING):
            result = await service._invoke_remote_agent(
                uaid=uaid,
                parameters={"test": "data"},
                interaction_type="request",
                bearer_token=None,  # Explicitly None - auth middleware didn't extract token
            )

        # Assert
        assert result == {"result": "success"}
        # Verify no Authorization header was sent
        assert "Authorization" not in captured_headers, "Should not include Authorization header when bearer_token is None"
        # Verify warning was logged about missing token
        assert any("Cross-gateway call without bearer token" in record.message for record in caplog.records)
        assert any("Remote gateway will receive unauthenticated request" in record.message for record in caplog.records)

    async def test_cross_gateway_call_with_forward_auth_disabled_logs_info(self, service, monkeypatch, caplog):
        """
        Test that disabling UAID_FORWARD_AUTH logs info instead of warning.

        Given: UAID_FORWARD_AUTH=false and bearer_token is available
        When: _invoke_remote_agent is called
        Then: Should log INFO (not WARNING) about forwarding being disabled
        """
        # First-Party
        from unittest.mock import AsyncMock, MagicMock
        import logging

        # Arrange
        monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_allowed_domains", ["example.com"])
        monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_forward_auth", False)  # Disabled

        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=agent.example.com"

        # Mock HTTP response
        captured_headers = {}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "success"}

        async def mock_post(*args, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            return mock_response

        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=mock_post)

        async def mock_get_http_client():
            return mock_client

        monkeypatch.setattr("mcpgateway.services.http_client_service.get_http_client", mock_get_http_client)

        # Act - call with bearer_token but forwarding disabled
        with caplog.at_level(logging.INFO):
            result = await service._invoke_remote_agent(
                uaid=uaid,
                parameters={"test": "data"},
                interaction_type="request",
                bearer_token=_make_test_jwt(),  # Token available but forwarding disabled
            )

        # Assert
        assert result == {"result": "success"}
        # Verify token was NOT forwarded
        assert "Authorization" not in captured_headers, "Should not forward token when UAID_FORWARD_AUTH=false"
        # Verify INFO log about forwarding being disabled
        assert any("UAID_FORWARD_AUTH disabled" in record.message for record in caplog.records)
        assert any("not forwarding bearer token" in record.message for record in caplog.records)


class TestTokenTypeFiltering:
    """Tests for JWT token type filtering before cross-gateway forwarding."""

    @pytest.fixture
    def service(self):
        """Create A2AAgentService instance for testing."""
        return A2AAgentService()

    async def test_cf_sess_token_not_forwarded(self, service, monkeypatch, caplog):
        """
        SECURITY: Local session tokens (cf_sess_*) must NOT be forwarded to remote gateways.

        Given: A cf_sess_ token is provided
        When: _invoke_remote_agent is called
        Then: Should NOT include Authorization header and should log info
        """
        # First-Party
        from unittest.mock import AsyncMock, MagicMock
        import logging

        # Arrange
        monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_allowed_domains", ["example.com"])
        monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_forward_auth", True)

        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=agent.example.com"
        sess_token = "cf_sess_abc123def456"

        captured_headers = {}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "success"}

        async def mock_post(*args, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            return mock_response

        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=mock_post)

        async def mock_get_http_client():
            return mock_client

        monkeypatch.setattr("mcpgateway.services.http_client_service.get_http_client", mock_get_http_client)

        # Act
        with caplog.at_level(logging.INFO):
            result = await service._invoke_remote_agent(
                uaid=uaid,
                parameters={"test": "data"},
                interaction_type="request",
                bearer_token=sess_token,
            )

        # Assert
        assert result == {"result": "success"}
        assert "Authorization" not in captured_headers, "SECURITY: cf_sess_ token must NOT be forwarded to remote gateways"
        assert any("Non-JWT token detected" in record.message for record in caplog.records)

    async def test_cf_pat_token_not_forwarded(self, service, monkeypatch, caplog):
        """
        SECURITY: Personal access tokens (cf_pat_*) must NOT be forwarded to remote gateways.

        Given: A cf_pat_ token is provided
        When: _invoke_remote_agent is called
        Then: Should NOT include Authorization header
        """
        # First-Party
        from unittest.mock import AsyncMock, MagicMock
        import logging

        # Arrange
        monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_allowed_domains", ["example.com"])
        monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_forward_auth", True)

        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=agent.example.com"
        pat_token = "cf_pat_xyz789uvw123"

        captured_headers = {}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "success"}

        async def mock_post(*args, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            return mock_response

        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=mock_post)

        async def mock_get_http_client():
            return mock_client

        monkeypatch.setattr("mcpgateway.services.http_client_service.get_http_client", mock_get_http_client)

        # Act
        with caplog.at_level(logging.INFO):
            result = await service._invoke_remote_agent(
                uaid=uaid,
                parameters={"test": "data"},
                interaction_type="request",
                bearer_token=pat_token,
            )

        # Assert
        assert result == {"result": "success"}
        assert "Authorization" not in captured_headers, "SECURITY: cf_pat_ token must NOT be forwarded to remote gateways"

    async def test_malformed_jwt_not_forwarded(self, service, monkeypatch, caplog):
        """
        SECURITY: Malformed JWT-like tokens must NOT be forwarded.

        Given: A token with 2 dots but invalid base64 parts
        When: _invoke_remote_agent is called
        Then: Should NOT include Authorization header
        """
        # First-Party
        from unittest.mock import AsyncMock, MagicMock
        import logging

        # Arrange
        monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_allowed_domains", ["example.com"])
        monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_forward_auth", True)

        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=agent.example.com"
        bad_token = "header.!!!invalid!!!.signature"

        captured_headers = {}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "success"}

        async def mock_post(*args, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            return mock_response

        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=mock_post)

        async def mock_get_http_client():
            return mock_client

        monkeypatch.setattr("mcpgateway.services.http_client_service.get_http_client", mock_get_http_client)

        # Act
        with caplog.at_level(logging.INFO):
            result = await service._invoke_remote_agent(
                uaid=uaid,
                parameters={"test": "data"},
                interaction_type="request",
                bearer_token=bad_token,
            )

        # Assert
        assert result == {"result": "success"}
        assert "Authorization" not in captured_headers, "SECURITY: malformed JWT must NOT be forwarded"

    async def test_valid_jwt_is_forwarded(self, service, monkeypatch):
        """
        Verify that valid JWT tokens ARE forwarded.

        Given: A valid JWT token (3 base64url parts)
        When: _invoke_remote_agent is called
        Then: Should include Authorization: Bearer {token} header
        """
        # Third-Party
        import base64

        # First-Party
        from unittest.mock import AsyncMock, MagicMock

        # Arrange
        monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_allowed_domains", ["example.com"])
        monkeypatch.setattr("mcpgateway.services.a2a_service.settings.uaid_forward_auth", True)

        uaid = "uaid:aid:9BjK3mP7xQv;uid=0;registry=context-forge;proto=a2a;nativeId=agent.example.com"
        # Create a valid-looking JWT (base64url-encoded parts)
        valid_jwt = (
            base64.urlsafe_b64encode(b'{"alg":"HS256"}').decode().rstrip("=")
            + "."
            + base64.urlsafe_b64encode(b'{"sub":"user"}').decode().rstrip("=")
            + "."
            + base64.urlsafe_b64encode(b"signature").decode().rstrip("=")
        )

        captured_headers = {}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "success"}

        async def mock_post(*args, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            return mock_response

        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=mock_post)

        async def mock_get_http_client():
            return mock_client

        monkeypatch.setattr("mcpgateway.services.http_client_service.get_http_client", mock_get_http_client)

        # Act
        result = await service._invoke_remote_agent(
            uaid=uaid,
            parameters={"test": "data"},
            interaction_type="request",
            bearer_token=valid_jwt,
        )

        # Assert
        assert result == {"result": "success"}
        assert "Authorization" in captured_headers
        assert captured_headers["Authorization"] == f"Bearer {valid_jwt}"

    def test_empty_token_is_not_jwt(self, service):
        from mcpgateway.services.a2a_service import _is_jwt_token

        assert not _is_jwt_token("")

    def test_token_with_wrong_part_count_is_not_jwt(self, service):
        from mcpgateway.services.a2a_service import _is_jwt_token

        assert not _is_jwt_token("one.two")

    def test_token_with_empty_part_is_not_jwt(self, service):
        from mcpgateway.services.a2a_service import _is_jwt_token

        assert not _is_jwt_token("header..signature")


class TestNativeIdPathRejection:
    """Tests for path component rejection in UAID native_id parsing."""

    @pytest.fixture
    def service(self):
        """Create A2AAgentService instance for testing."""
        return A2AAgentService()

    async def test_register_rejects_native_id_with_path(self, service, monkeypatch):
        """
        SECURITY: Registration must reject endpoint URLs with paths in native_id.

        Given: endpoint_url contains a path component
        When: register_agent is called with generate_uaid=True
        Then: Should raise ValueError with path rejection message
        """
        # Standard
        from unittest.mock import MagicMock, patch

        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        agent_data = MagicMock()
        agent_data.name = "test-agent"
        agent_data.slug = "test-agent"
        agent_data.endpoint_url = "https://example.com/a2a/path"
        agent_data.agent_type = "http"
        agent_data.protocol_version = "1.0"
        agent_data.description = "Test"
        agent_data.capabilities = []
        agent_data.config = {}
        agent_data.tags = []
        agent_data.auth_type = None
        agent_data.auth_value = None
        agent_data.auth_headers = None
        agent_data.generate_uaid = True
        agent_data.uaid_registry = "context-forge"
        agent_data.version = "1.0.0"
        agent_data.uaid_protocol = "a2a"
        agent_data.uaid_skills = []
        agent_data.uaid_native_id_override = None

        mock_db = MagicMock()

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=None):
            with pytest.raises(ValueError, match="cannot contain path components"):
                await service.register_agent(
                    mock_db,
                    agent_data,
                )

    async def test_register_rejects_native_id_with_query_string(self, service, monkeypatch):
        from unittest.mock import MagicMock, patch

        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        agent_data = MagicMock()
        agent_data.name = "test-agent"
        agent_data.slug = "test-agent"
        agent_data.endpoint_url = "https://example.com?foo=bar"
        agent_data.agent_type = "http"
        agent_data.protocol_version = "1.0"
        agent_data.description = "Test"
        agent_data.capabilities = []
        agent_data.config = {}
        agent_data.tags = []
        agent_data.auth_type = None
        agent_data.auth_value = None
        agent_data.auth_headers = None
        agent_data.generate_uaid = True
        agent_data.uaid_registry = "context-forge"
        agent_data.version = "1.0.0"
        agent_data.uaid_protocol = "a2a"
        agent_data.uaid_skills = []
        agent_data.uaid_native_id_override = None

        mock_db = MagicMock()

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=None):
            with pytest.raises(ValueError, match="cannot contain query strings"):
                await service.register_agent(mock_db, agent_data)

    async def test_register_rejects_native_id_with_fragment(self, service, monkeypatch):
        from unittest.mock import MagicMock, patch

        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        agent_data = MagicMock()
        agent_data.name = "test-agent"
        agent_data.slug = "test-agent"
        agent_data.endpoint_url = "https://example.com#frag"
        agent_data.agent_type = "http"
        agent_data.protocol_version = "1.0"
        agent_data.description = "Test"
        agent_data.capabilities = []
        agent_data.config = {}
        agent_data.tags = []
        agent_data.auth_type = None
        agent_data.auth_value = None
        agent_data.auth_headers = None
        agent_data.generate_uaid = True
        agent_data.uaid_registry = "context-forge"
        agent_data.version = "1.0.0"
        agent_data.uaid_protocol = "a2a"
        agent_data.uaid_skills = []
        agent_data.uaid_native_id_override = None

        mock_db = MagicMock()

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=None):
            with pytest.raises(ValueError, match="cannot contain fragments"):
                await service.register_agent(mock_db, agent_data)

    async def test_register_rejects_disallowed_native_id_override_domain(self, service, monkeypatch):
        from unittest.mock import MagicMock, patch

        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        agent_data = MagicMock()
        agent_data.name = "test-agent"
        agent_data.slug = "test-agent"
        agent_data.endpoint_url = "https://example.com"
        agent_data.agent_type = "http"
        agent_data.protocol_version = "1.0"
        agent_data.description = "Test"
        agent_data.capabilities = []
        agent_data.config = {}
        agent_data.tags = []
        agent_data.auth_type = None
        agent_data.auth_value = None
        agent_data.auth_headers = None
        agent_data.generate_uaid = True
        agent_data.uaid_registry = "context-forge"
        agent_data.version = "1.0.0"
        agent_data.uaid_protocol = "a2a"
        agent_data.uaid_skills = []
        agent_data.uaid_native_id_override = "https://evil.example.net"

        mock_db = MagicMock()

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=None):
            with pytest.raises(ValueError, match="not in UAID_ALLOWED_DOMAINS"):
                await service.register_agent(mock_db, agent_data)

    async def test_register_rejects_native_id_override_with_path(self, service, monkeypatch):
        """
        SECURITY: Registration must reject uaid_native_id_override with paths.

        Given: uaid_native_id_override contains a path component
        When: register_agent is called with generate_uaid=True
        Then: Should raise ValueError with path rejection message
        """
        # Standard
        from unittest.mock import MagicMock, patch

        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        agent_data = MagicMock()
        agent_data.name = "test-agent"
        agent_data.slug = "test-agent"
        agent_data.endpoint_url = "https://example.com"
        agent_data.agent_type = "http"
        agent_data.protocol_version = "1.0"
        agent_data.description = "Test"
        agent_data.capabilities = []
        agent_data.config = {}
        agent_data.tags = []
        agent_data.auth_type = None
        agent_data.auth_value = None
        agent_data.auth_headers = None
        agent_data.generate_uaid = True
        agent_data.uaid_registry = "context-forge"
        agent_data.version = "1.0.0"
        agent_data.uaid_protocol = "a2a"
        agent_data.uaid_skills = []
        agent_data.uaid_native_id_override = "example.com/a2a/override"

        mock_db = MagicMock()

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=None):
            with pytest.raises(ValueError, match="cannot contain path components"):
                await service.register_agent(
                    mock_db,
                    agent_data,
                )

    async def test_register_rejects_schemeless_native_id_with_path(self, service, monkeypatch):
        """
        SECURITY: Registration must reject schemeless endpoint URLs with paths.

        Given: endpoint_url has no scheme but contains a path
        When: register_agent is called with generate_uaid=True
        Then: Should raise ValueError with path rejection message
        """
        # Standard
        from unittest.mock import MagicMock, patch

        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        agent_data = MagicMock()
        agent_data.name = "test-agent"
        agent_data.slug = "test-agent"
        agent_data.endpoint_url = "example.com/a2a/path"
        agent_data.agent_type = "http"
        agent_data.protocol_version = "1.0"
        agent_data.description = "Test"
        agent_data.capabilities = []
        agent_data.config = {}
        agent_data.tags = []
        agent_data.auth_type = None
        agent_data.auth_value = None
        agent_data.auth_headers = None
        agent_data.generate_uaid = True
        agent_data.uaid_registry = "context-forge"
        agent_data.version = "1.0.0"
        agent_data.uaid_protocol = "a2a"
        agent_data.uaid_skills = []
        agent_data.uaid_native_id_override = None

        mock_db = MagicMock()

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=None):
            with pytest.raises(ValueError, match="cannot contain path components"):
                await service.register_agent(
                    mock_db,
                    agent_data,
                )

    async def test_update_rejects_native_id_with_path(self, service, monkeypatch):
        """
        SECURITY: Update must reject endpoint URLs with paths in native_id.

        Given: An existing agent without UAID, endpoint_url updated with path
        When: update_agent is called with generate_uaid=True
        Then: Should raise ValueError with path rejection message
        """
        # Standard
        from unittest.mock import MagicMock, patch

        # First-Party
        from mcpgateway.schemas import A2AAgentUpdate

        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        # Create a mock agent without UAID (simulating pre-existing agent with bad endpoint)
        agent = MagicMock()
        agent.uaid = None
        agent.name = "test-agent"
        agent.version = 1
        agent.endpoint_url = "https://example.com/a2a/path"
        agent.team_id = None
        agent.auth_type = None
        agent.auth_value = None
        agent.auth_query_params = None

        agent_data = A2AAgentUpdate(
            endpoint_url="https://example.com/a2a/path",
            generate_uaid=True,
            uaid_registry="context-forge",
            version="1.0.0",
            uaid_protocol="a2a",
        )

        mock_db = MagicMock()

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=agent):
            # ValueError from path rejection is wrapped in A2AAgentError by outer try/except
            with pytest.raises(A2AAgentError, match="cannot contain path components"):
                await service.update_agent(
                    mock_db,
                    agent_id="agent-123",
                    agent_data=agent_data,
                )

    async def test_update_rejects_native_id_with_query_string(self, service, monkeypatch):
        from unittest.mock import MagicMock, patch

        from mcpgateway.schemas import A2AAgentUpdate

        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        agent = MagicMock()
        agent.uaid = None
        agent.name = "test-agent"
        agent.version = 1
        agent.endpoint_url = "https://example.com"
        agent.team_id = None
        agent.auth_type = None
        agent.auth_value = None
        agent.auth_query_params = None

        agent_data = A2AAgentUpdate(
            endpoint_url="https://example.com?foo=bar",
            generate_uaid=True,
            uaid_registry="context-forge",
            version="1.0.0",
            uaid_protocol="a2a",
        )

        mock_db = MagicMock()

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=agent):
            with pytest.raises(A2AAgentError, match="cannot contain query strings"):
                await service.update_agent(mock_db, agent_id="agent-123", agent_data=agent_data)

    async def test_update_rejects_native_id_with_fragment(self, service, monkeypatch):
        from unittest.mock import MagicMock, patch

        from mcpgateway.schemas import A2AAgentUpdate

        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        agent = MagicMock()
        agent.uaid = None
        agent.name = "test-agent"
        agent.version = 1
        agent.endpoint_url = "https://example.com"
        agent.team_id = None
        agent.auth_type = None
        agent.auth_value = None
        agent.auth_query_params = None

        agent_data = A2AAgentUpdate(
            endpoint_url="https://example.com#frag",
            generate_uaid=True,
            uaid_registry="context-forge",
            version="1.0.0",
            uaid_protocol="a2a",
        )

        mock_db = MagicMock()

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=agent):
            with pytest.raises(A2AAgentError, match="cannot contain fragments"):
                await service.update_agent(mock_db, agent_id="agent-123", agent_data=agent_data)

    async def test_update_rejects_disallowed_native_id_override_domain(self, service, monkeypatch):
        from unittest.mock import MagicMock, patch

        from mcpgateway.schemas import A2AAgentUpdate

        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        agent = MagicMock()
        agent.uaid = None
        agent.name = "test-agent"
        agent.version = 1
        agent.endpoint_url = "https://example.com"
        agent.team_id = None
        agent.auth_type = None
        agent.auth_value = None
        agent.auth_query_params = None

        agent_data = A2AAgentUpdate(
            endpoint_url="https://example.com",
            generate_uaid=True,
            uaid_native_id_override="https://evil.example.net",
            uaid_registry="context-forge",
            version="1.0.0",
            uaid_protocol="a2a",
        )

        mock_db = MagicMock()

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=agent):
            with pytest.raises(A2AAgentError, match="not in UAID_ALLOWED_DOMAINS"):
                await service.update_agent(mock_db, agent_id="agent-123", agent_data=agent_data)

    async def test_update_sets_uaid_native_id_on_success(self, service, monkeypatch):
        from unittest.mock import MagicMock, patch

        from mcpgateway.schemas import A2AAgentUpdate

        monkeypatch.setattr("mcpgateway.config.settings.uaid_allowed_domains", ["example.com"])
        monkeypatch.setattr("mcpgateway.config.settings.uaid_allow_all_domains", False)

        agent = MagicMock()
        agent.uaid = None
        agent.name = "test-agent"
        agent.version = 1
        agent.endpoint_url = "https://example.com"
        agent.team_id = None
        agent.auth_type = None
        agent.auth_value = None
        agent.auth_query_params = None

        agent_data = A2AAgentUpdate(
            endpoint_url="https://example.com",
            generate_uaid=True,
            uaid_registry="context-forge",
            uaid_protocol="a2a",
        )

        mock_db = MagicMock()

        with patch("mcpgateway.services.a2a_service.get_for_update", return_value=agent):
            with patch("mcpgateway.utils.uaid.generate_uaid", return_value="uaid:aid:123;uid=0;registry=context-forge;proto=a2a;nativeId=example.com"):
                with patch("mcpgateway.services.a2a_service._get_registry_cache") as mock_cache:
                    from unittest.mock import AsyncMock

                    mock_cache.return_value.invalidate_agents = AsyncMock()
                    with patch("mcpgateway.cache.admin_stats_cache.admin_stats_cache.invalidate_tags", new=AsyncMock()):
                        with patch("mcpgateway.services.tool_service.tool_service.update_tool_from_a2a_agent", new=AsyncMock()):
                            with patch.object(service, "convert_agent_to_read", return_value=agent):
                                with patch.object(mock_db, "commit", MagicMock()), patch.object(mock_db, "refresh", MagicMock()):
                                    result = await service.update_agent(mock_db, agent_id="agent-123", agent_data=agent_data)

        assert result is agent
        assert agent.uaid_native_id == "https://example.com"
