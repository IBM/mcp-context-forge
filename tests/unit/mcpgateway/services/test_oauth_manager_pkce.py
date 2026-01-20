# -*- coding: utf-8 -*-
"""Test OAuth Manager PKCE Support (RFC 7636).

This test suite validates PKCE (Proof Key for Code Exchange) implementation
in the OAuth Manager following TDD Red Phase.

Tests will FAIL until implementation is complete.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from mcpgateway.services.oauth_manager import OAuthManager, OAuthError


class TestPKCEGeneration:
    """Test PKCE parameter generation."""

    def test_generate_pkce_params_returns_required_fields(self):
        """Test that PKCE generation returns all required fields."""
        manager = OAuthManager()

        pkce = manager._generate_pkce_params()

        assert "code_verifier" in pkce
        assert "code_challenge" in pkce
        assert "code_challenge_method" in pkce
        assert pkce["code_challenge_method"] == "S256"

    def test_generate_pkce_params_code_verifier_length(self):
        """Test that code_verifier meets RFC 7636 length requirements (43-128 chars)."""
        manager = OAuthManager()

        pkce = manager._generate_pkce_params()

        assert 43 <= len(pkce["code_verifier"]) <= 128

    def test_generate_pkce_params_code_verifier_charset(self):
        """Test that code_verifier uses unreserved characters only."""
        manager = OAuthManager()

        pkce = manager._generate_pkce_params()

        # RFC 7636: unreserved characters = [A-Z] / [a-z] / [0-9] / "-" / "." / "_" / "~"
        allowed_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
        verifier_chars = set(pkce["code_verifier"])
        assert verifier_chars.issubset(allowed_chars)

    def test_generate_pkce_params_code_challenge_is_base64url(self):
        """Test that code_challenge is base64url encoded."""
        manager = OAuthManager()

        pkce = manager._generate_pkce_params()

        # Base64url uses [A-Za-z0-9-_] (no padding)
        allowed_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
        challenge_chars = set(pkce["code_challenge"])
        assert challenge_chars.issubset(allowed_chars)

    def test_generate_pkce_params_is_unique(self):
        """Test that each call generates unique parameters."""
        manager = OAuthManager()

        pkce1 = manager._generate_pkce_params()
        pkce2 = manager._generate_pkce_params()

        assert pkce1["code_verifier"] != pkce2["code_verifier"]
        assert pkce1["code_challenge"] != pkce2["code_challenge"]

    def test_generate_pkce_params_challenge_is_sha256_of_verifier(self):
        """Test that code_challenge is SHA256 hash of code_verifier."""
        import base64
        import hashlib

        manager = OAuthManager()

        pkce = manager._generate_pkce_params()

        # Manually compute expected challenge
        expected_challenge = base64.urlsafe_b64encode(hashlib.sha256(pkce["code_verifier"].encode("utf-8")).digest()).decode("utf-8").rstrip("=")

        assert pkce["code_challenge"] == expected_challenge


class TestAuthorizationURLWithPKCE:
    """Test authorization URL generation with PKCE parameters."""

    def test_create_authorization_url_with_pkce_includes_challenge(self):
        """Test that authorization URL includes code_challenge parameter."""
        manager = OAuthManager()

        credentials = {"client_id": "test-client", "authorization_url": "https://as.example.com/authorize", "redirect_uri": "http://localhost:4444/callback", "scopes": ["mcp:read", "mcp:tools"]}
        state = "test-state"
        code_challenge = "test-challenge"
        code_challenge_method = "S256"

        auth_url = manager._create_authorization_url_with_pkce(credentials, state, code_challenge, code_challenge_method)

        assert "code_challenge=test-challenge" in auth_url
        assert "code_challenge_method=S256" in auth_url

    def test_create_authorization_url_with_pkce_includes_all_params(self):
        """Test that authorization URL includes all required OAuth parameters."""
        manager = OAuthManager()

        credentials = {"client_id": "test-client", "authorization_url": "https://as.example.com/authorize", "redirect_uri": "http://localhost:4444/callback", "scopes": ["mcp:read"]}
        state = "test-state"
        code_challenge = "test-challenge"

        auth_url = manager._create_authorization_url_with_pkce(credentials, state, code_challenge, "S256")

        assert "response_type=code" in auth_url
        assert "client_id=test-client" in auth_url
        assert "redirect_uri=" in auth_url
        assert "state=test-state" in auth_url
        assert "scope=mcp%3Aread" in auth_url or "scope=mcp:read" in auth_url

    def test_create_authorization_url_with_pkce_handles_multiple_scopes(self):
        """Test that multiple scopes are properly encoded."""
        manager = OAuthManager()

        credentials = {
            "client_id": "test-client",
            "authorization_url": "https://as.example.com/authorize",
            "redirect_uri": "http://localhost:4444/callback",
            "scopes": ["mcp:read", "mcp:tools", "mcp:resources"],
        }

        auth_url = manager._create_authorization_url_with_pkce(credentials, "state", "challenge", "S256")

        # Scopes should be space-separated
        assert "scope=" in auth_url


class TestStoreAuthorizationStateWithPKCE:
    """Test storing authorization state with code_verifier."""

    @pytest.mark.asyncio
    async def test_store_authorization_state_includes_code_verifier(self):
        """Test that state storage includes code_verifier for PKCE."""
        manager = OAuthManager()

        gateway_id = "test-gateway-123"
        state = "test-state"
        code_verifier = "test-verifier"

        # Patch module-level _state_lock, not instance
        with patch("mcpgateway.services.oauth_manager._state_lock"):
            await manager._store_authorization_state(gateway_id, state, code_verifier)

        # This test validates the method signature accepts code_verifier
        # Actual storage validation happens in integration tests

    @pytest.mark.asyncio
    async def test_store_authorization_state_without_code_verifier_still_works(self):
        """Test backward compatibility - state can be stored without code_verifier."""
        manager = OAuthManager()

        gateway_id = "test-gateway-123"
        state = "test-state"

        # Should not raise error
        with patch("mcpgateway.services.oauth_manager._state_lock"):
            await manager._store_authorization_state(gateway_id, state)


class TestValidateAndRetrieveState:
    """Test state validation that returns code_verifier."""

    @pytest.mark.asyncio
    async def test_validate_and_retrieve_state_returns_code_verifier(self):
        """Test that state validation returns code_verifier."""
        manager = OAuthManager()

        gateway_id = "test-gateway-123"
        state = "test-state"

        # Mock in-memory state storage
        from mcpgateway.services.oauth_manager import _oauth_states, _state_lock
        from datetime import datetime, timedelta, timezone

        state_key = f"oauth:state:{gateway_id}:{state}"
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=300)

        async with _state_lock:
            _oauth_states[state_key] = {"state": state, "gateway_id": gateway_id, "code_verifier": "test-verifier-123", "expires_at": expires_at.isoformat(), "used": False}

        result = await manager._validate_and_retrieve_state(gateway_id, state)

        assert result is not None
        assert result["code_verifier"] == "test-verifier-123"
        assert result["state"] == state
        assert result["gateway_id"] == gateway_id

    @pytest.mark.asyncio
    async def test_validate_and_retrieve_state_returns_none_if_expired(self):
        """Test that expired state returns None."""
        manager = OAuthManager()

        gateway_id = "test-gateway-123"
        state = "test-state"

        from mcpgateway.services.oauth_manager import _oauth_states, _state_lock
        from datetime import datetime, timedelta, timezone

        state_key = f"oauth:state:{gateway_id}:{state}"
        expires_at = datetime.now(timezone.utc) - timedelta(seconds=60)  # Expired

        async with _state_lock:
            _oauth_states[state_key] = {"state": state, "gateway_id": gateway_id, "code_verifier": "test-verifier", "expires_at": expires_at.isoformat(), "used": False}

        result = await manager._validate_and_retrieve_state(gateway_id, state)

        assert result is None

    @pytest.mark.asyncio
    async def test_validate_and_retrieve_state_single_use(self):
        """Test that state can only be used once."""
        manager = OAuthManager()

        gateway_id = "test-gateway-123"
        state = "test-state"

        from mcpgateway.services.oauth_manager import _oauth_states, _state_lock
        from datetime import datetime, timedelta, timezone

        state_key = f"oauth:state:{gateway_id}:{state}"
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=300)

        async with _state_lock:
            _oauth_states[state_key] = {"state": state, "gateway_id": gateway_id, "code_verifier": "test-verifier", "expires_at": expires_at.isoformat(), "used": False}

        # First retrieval should succeed
        result1 = await manager._validate_and_retrieve_state(gateway_id, state)
        assert result1 is not None

        # Second retrieval should fail (state consumed)
        result2 = await manager._validate_and_retrieve_state(gateway_id, state)
        assert result2 is None


class TestExchangeCodeForTokensWithPKCE:
    """Test token exchange with code_verifier."""

    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens_includes_code_verifier(self):
        """Test that token exchange includes code_verifier in request."""
        manager = OAuthManager()

        credentials = {"client_id": "test-client", "client_secret": "test-secret", "token_url": "https://as.example.com/token", "redirect_uri": "http://localhost:4444/callback"}
        code = "auth-code-123"
        code_verifier = "test-verifier-xyz"

        mock_response = {"access_token": "access-token-123", "token_type": "Bearer", "expires_in": 3600}

        # Create mock response
        mock_response_obj = MagicMock()
        mock_response_obj.status_code = 200
        mock_response_obj.json = MagicMock(return_value=mock_response)
        mock_response_obj.raise_for_status = MagicMock()
        mock_response_obj.headers = {"content-type": "application/json"}

        # Create mock client
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response_obj)

        with patch.object(manager, "_get_client", return_value=mock_client):
            result = await manager._exchange_code_for_tokens(credentials, code, code_verifier=code_verifier)

        # Verify code_verifier was included in request
        call_kwargs = mock_client.post.call_args[1]
        assert call_kwargs["data"]["code_verifier"] == code_verifier

    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens_without_code_verifier_works(self):
        """Test backward compatibility - token exchange without PKCE."""
        manager = OAuthManager()

        credentials = {"client_id": "test-client", "client_secret": "test-secret", "token_url": "https://as.example.com/token", "redirect_uri": "http://localhost:4444/callback"}
        code = "auth-code-123"

        mock_response = {"access_token": "access-token-123", "token_type": "Bearer", "expires_in": 3600}

        # Create mock response
        mock_response_obj = MagicMock()
        mock_response_obj.status_code = 200
        mock_response_obj.json = MagicMock(return_value=mock_response)
        mock_response_obj.raise_for_status = MagicMock()
        mock_response_obj.headers = {"content-type": "application/json"}

        # Create mock client
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response_obj)

        with patch.object(manager, "_get_client", return_value=mock_client):
            # Should not raise error
            result = await manager._exchange_code_for_tokens(credentials, code)

            assert result["access_token"] == "access-token-123"


class TestInitiateAuthorizationCodeFlowWithPKCE:
    """Test OAuth flow initiation with PKCE."""

    @pytest.mark.asyncio
    async def test_initiate_authorization_code_flow_generates_pkce(self):
        """Test that initiating flow generates PKCE parameters."""
        # Create manager with mock token_storage so _store_authorization_state is called
        mock_storage = MagicMock()
        manager = OAuthManager(token_storage=mock_storage)

        gateway_id = "test-gateway"
        credentials = {"client_id": "test-client", "authorization_url": "https://as.example.com/authorize", "redirect_uri": "http://localhost:4444/callback", "scopes": ["mcp:read"]}

        with (
            patch.object(manager, "_generate_pkce_params") as mock_pkce,
            patch.object(manager, "_generate_state") as mock_state,
            patch.object(manager, "_store_authorization_state") as mock_store,
            patch.object(manager, "_create_authorization_url_with_pkce") as mock_create_url,
        ):
            mock_pkce.return_value = {"code_verifier": "verifier", "code_challenge": "challenge", "code_challenge_method": "S256"}
            mock_state.return_value = "state-123"
            mock_store.return_value = None
            mock_create_url.return_value = "https://as.example.com/authorize?..."

            result = await manager.initiate_authorization_code_flow(gateway_id, credentials)

        # Verify PKCE was generated
        mock_pkce.assert_called_once()

        # Verify code_verifier was stored
        mock_store.assert_called_once()
        call_args = mock_store.call_args
        assert call_args[1]["code_verifier"] == "verifier"


class TestCompleteAuthorizationCodeFlowWithPKCE:
    """Test OAuth flow completion with PKCE validation."""

    @pytest.mark.asyncio
    async def test_complete_authorization_code_flow_retrieves_code_verifier(self):
        """Test that completing flow retrieves and uses code_verifier."""
        manager = OAuthManager()

        gateway_id = "test-gateway"
        code = "auth-code-123"
        state = "state-123"
        credentials = {"client_id": "test-client", "client_secret": "test-secret", "token_url": "https://as.example.com/token", "redirect_uri": "http://localhost:4444/callback"}

        with (
            patch.object(manager, "_validate_and_retrieve_state") as mock_validate,
            patch.object(manager, "_exchange_code_for_tokens") as mock_exchange,
            patch.object(manager, "_extract_user_id") as mock_extract,
        ):
            mock_validate.return_value = {"state": state, "gateway_id": gateway_id, "code_verifier": "verifier-xyz", "expires_at": "2025-12-31T23:59:59+00:00"}
            mock_exchange.return_value = {"access_token": "token", "expires_in": 3600}
            mock_extract.return_value = "user-123"

            result = await manager.complete_authorization_code_flow(gateway_id, code, state, credentials)

        # Verify code_verifier was passed to token exchange
        mock_exchange.assert_called_once()
        call_kwargs = mock_exchange.call_args[1]
        assert call_kwargs["code_verifier"] == "verifier-xyz"

    @pytest.mark.asyncio
    async def test_complete_authorization_code_flow_fails_with_invalid_state(self):
        """Test that invalid state causes flow to fail."""
        manager = OAuthManager()

        gateway_id = "test-gateway"
        code = "auth-code-123"
        state = "invalid-state"
        credentials = {"client_id": "test"}

        with patch.object(manager, "_validate_and_retrieve_state") as mock_validate:
            mock_validate.return_value = None  # Invalid state

            with pytest.raises(OAuthError, match="Invalid or expired state"):
                await manager.complete_authorization_code_flow(gateway_id, code, state, credentials)


class TestPKCESecurityProperties:
    """Test security properties of PKCE implementation."""

    def test_pkce_verifier_has_sufficient_entropy(self):
        """Test that code_verifier has sufficient cryptographic entropy."""
        manager = OAuthManager()

        # Generate multiple verifiers and check uniqueness
        verifiers = set()
        for _ in range(100):
            pkce = manager._generate_pkce_params()
            verifiers.add(pkce["code_verifier"])

        # All 100 should be unique
        assert len(verifiers) == 100

    def test_pkce_uses_s256_method_only(self):
        """Test that only S256 method is used (not plain)."""
        manager = OAuthManager()

        pkce = manager._generate_pkce_params()

        # RFC 7636 recommends S256, plain is discouraged
        assert pkce["code_challenge_method"] == "S256"
        assert pkce["code_challenge_method"] != "plain"

    def test_pkce_challenge_cannot_be_reversed_to_verifier(self):
        """Test that code_challenge is a one-way hash."""
        manager = OAuthManager()

        pkce = manager._generate_pkce_params()

        # Challenge should be different from verifier (it's a hash)
        assert pkce["code_challenge"] != pkce["code_verifier"]

        # Challenge should be shorter (SHA256 hash is 32 bytes = 43 chars base64url)
        assert len(pkce["code_challenge"]) == 43  # SHA256 base64url without padding


class TestRFC8707MultipleResources:
    """Test RFC 8707 multiple resource parameter support."""

    @pytest.mark.asyncio
    async def test_exchange_code_with_list_resource_sends_multiple_params(self):
        """Test that list resources are sent as multiple form parameters."""
        manager = OAuthManager()

        credentials = {
            "client_id": "test_client",
            "client_secret": "test_secret",
            "redirect_uri": "https://gateway.example.com/callback",
            "token_url": "https://oauth.example.com/token",
            "resource": ["https://api1.example.com", "https://api2.example.com"],
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json = MagicMock(return_value={"access_token": "test_token", "token_type": "Bearer"})
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(manager, "_get_client", return_value=mock_client):
            await manager._exchange_code_for_tokens(credentials, "auth_code", "code_verifier")

            # Verify the request was made
            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args

            # When resource is a list, data should be list of tuples
            form_data = call_args[1]["data"]
            assert isinstance(form_data, list), "Form data should be list of tuples for multiple resources"

            # Count resource entries
            resource_entries = [entry for entry in form_data if entry[0] == "resource"]
            assert len(resource_entries) == 2, "Should have two resource parameters"
            assert ("resource", "https://api1.example.com") in form_data
            assert ("resource", "https://api2.example.com") in form_data

    @pytest.mark.asyncio
    async def test_refresh_token_with_list_resource_sends_multiple_params(self):
        """Test that list resources in refresh are sent as multiple form parameters."""
        manager = OAuthManager()

        credentials = {
            "client_id": "test_client",
            "client_secret": "test_secret",
            "token_url": "https://oauth.example.com/token",
            "resource": ["https://api1.example.com", "https://api2.example.com"],
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"access_token": "new_token", "expires_in": 3600})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(manager, "_get_client", return_value=mock_client):
            await manager.refresh_token("refresh_token", credentials)

            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args

            # When resource is a list, data should be list of tuples
            form_data = call_args[1]["data"]
            assert isinstance(form_data, list), "Form data should be list of tuples for multiple resources"

            # Count resource entries
            resource_entries = [entry for entry in form_data if entry[0] == "resource"]
            assert len(resource_entries) == 2, "Should have two resource parameters"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
