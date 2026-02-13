# -*- coding: utf-8 -*-
"""Test OAuth Manager PKCE Support (RFC 7636).

This test suite validates PKCE (Proof Key for Code Exchange) implementation
in the OAuth Manager following TDD Red Phase.

Tests will FAIL until implementation is complete.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
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
    async def test_validate_and_retrieve_state_returns_code_verifier(self, monkeypatch):
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

        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="memory"))
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
    async def test_validate_and_retrieve_state_single_use(self, monkeypatch):
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
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="memory"))
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


def _make_response(*, status_code=200, headers=None, text="", json_data=None, json_exc=None):
    response = MagicMock()
    response.status_code = status_code
    response.headers = headers or {}
    response.text = text
    if json_exc is not None:
        response.json = MagicMock(side_effect=json_exc)
    elif json_data is not None:
        response.json = MagicMock(return_value=json_data)
    else:
        response.json = MagicMock(return_value={})
    response.raise_for_status = MagicMock()
    return response


class TestOAuthManagerRedisClient:
    @pytest.mark.asyncio
    async def test_get_redis_client_cached(self, monkeypatch):
        import mcpgateway.services.oauth_manager as om

        monkeypatch.setattr(om, "_REDIS_INITIALIZED", False)
        monkeypatch.setattr(om, "_redis_client", None)
        monkeypatch.setattr(
            om,
            "get_settings",
            lambda: SimpleNamespace(cache_type="redis", redis_url="redis://localhost"),
        )

        fake_redis = MagicMock()
        get_shared = AsyncMock(return_value=fake_redis)
        monkeypatch.setattr(om, "_get_shared_redis_client", get_shared)

        client = await om._get_redis_client()
        assert client is fake_redis

        # Second call should use cached client
        client2 = await om._get_redis_client()
        assert client2 is fake_redis
        assert get_shared.call_count == 1

    @pytest.mark.asyncio
    async def test_get_redis_client_error_falls_back(self, monkeypatch):
        import mcpgateway.services.oauth_manager as om

        monkeypatch.setattr(om, "_REDIS_INITIALIZED", False)
        monkeypatch.setattr(om, "_redis_client", "stale")
        monkeypatch.setattr(
            om,
            "get_settings",
            lambda: SimpleNamespace(cache_type="redis", redis_url="redis://localhost"),
        )
        monkeypatch.setattr(om, "_get_shared_redis_client", AsyncMock(side_effect=RuntimeError("boom")))

        client = await om._get_redis_client()
        assert client is None
        assert om._REDIS_INITIALIZED is True


class TestOAuthManagerAccessToken:
    @pytest.mark.asyncio
    async def test_get_client_uses_shared_http_client(self, monkeypatch):
        manager = OAuthManager()
        fake_client = MagicMock()
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_http_client", AsyncMock(return_value=fake_client))

        assert await manager._get_client() is fake_client

    @pytest.mark.asyncio
    async def test_get_access_token_dispatches_flows(self, monkeypatch):
        manager = OAuthManager()
        monkeypatch.setattr(manager, "_client_credentials_flow", AsyncMock(return_value="tok"))
        token = await manager.get_access_token({"grant_type": "client_credentials"})
        assert token == "tok"

        monkeypatch.setattr(manager, "_password_flow", AsyncMock(return_value="pwdtok"))
        token = await manager.get_access_token({"grant_type": "password"})
        assert token == "pwdtok"

    @pytest.mark.asyncio
    async def test_get_access_token_authorization_code_fallback_error(self, monkeypatch):
        manager = OAuthManager()
        monkeypatch.setattr(manager, "_client_credentials_flow", AsyncMock(side_effect=RuntimeError("nope")))

        with pytest.raises(OAuthError, match="Authorization code flow cannot be used"):
            await manager.get_access_token({"grant_type": "authorization_code"})

    @pytest.mark.asyncio
    async def test_get_access_token_unsupported_grant(self):
        manager = OAuthManager()
        with pytest.raises(ValueError, match="Unsupported grant type"):
            await manager.get_access_token({"grant_type": "unsupported"})


class TestOAuthManagerClientCredentialsFlow:
    @pytest.mark.asyncio
    async def test_client_credentials_form_encoded_success_and_decrypt(self, monkeypatch):
        manager = OAuthManager(max_retries=1)
        long_secret = "x" * 60
        credentials = {"client_id": "cid", "client_secret": long_secret, "token_url": "https://auth.example.com/token", "scopes": ["read"]}

        decryptor = MagicMock()
        decryptor.decrypt_secret_async = AsyncMock(return_value="decrypted")
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_encryption_service", lambda _s: decryptor)
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(auth_encryption_secret="secret"))

        response = _make_response(
            headers={"content-type": "application/x-www-form-urlencoded"},
            text="access_token=abc&token_type=Bearer",
        )
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        token = await manager._client_credentials_flow(credentials)
        assert token == "abc"
        call_data = client.post.call_args[1]["data"]
        assert call_data["client_secret"] == "decrypted"

    @pytest.mark.asyncio
    async def test_client_credentials_json_parse_error_raises(self, monkeypatch):
        manager = OAuthManager(max_retries=1)
        credentials = {"client_id": "cid", "client_secret": "secret", "token_url": "https://auth.example.com/token"}

        response = _make_response(
            headers={"content-type": "application/json"},
            text="nope",
            json_exc=ValueError("bad json"),
        )
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        with pytest.raises(OAuthError, match="No access_token"):
            await manager._client_credentials_flow(credentials)

    @pytest.mark.asyncio
    async def test_client_credentials_http_error_raises(self, monkeypatch):
        manager = OAuthManager(max_retries=1)
        credentials = {"client_id": "cid", "client_secret": "secret", "token_url": "https://auth.example.com/token"}

        response = _make_response(headers={"content-type": "application/json"}, json_data={"access_token": "x"})
        response.raise_for_status.side_effect = httpx.HTTPError("bad")
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        with pytest.raises(OAuthError, match="Failed to obtain access token"):
            await manager._client_credentials_flow(credentials)


class TestOAuthManagerPasswordFlow:
    @pytest.mark.asyncio
    async def test_password_flow_requires_username_password(self):
        manager = OAuthManager()
        credentials = {"token_url": "https://auth.example.com/token"}
        with pytest.raises(OAuthError, match="Username and password are required"):
            await manager._password_flow(credentials)

    @pytest.mark.asyncio
    async def test_password_flow_form_encoded_success(self, monkeypatch):
        manager = OAuthManager(max_retries=1)
        long_secret = "y" * 60
        credentials = {
            "client_id": "cid",
            "client_secret": long_secret,
            "token_url": "https://auth.example.com/token",
            "username": "user",
            "password": "pass",
        }

        decryptor = MagicMock()
        decryptor.decrypt_secret_async = AsyncMock(return_value=None)
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_encryption_service", lambda _s: decryptor)
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(auth_encryption_secret="secret"))

        response = _make_response(
            headers={"content-type": "application/x-www-form-urlencoded"},
            text="access_token=pwdtok&token_type=Bearer",
        )
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        token = await manager._password_flow(credentials)
        assert token == "pwdtok"

    @pytest.mark.asyncio
    async def test_password_flow_json_parse_error_raises(self, monkeypatch):
        manager = OAuthManager(max_retries=1)
        credentials = {
            "token_url": "https://auth.example.com/token",
            "username": "user",
            "password": "pass",
        }

        response = _make_response(
            headers={"content-type": "application/json"},
            text="nope",
            json_exc=ValueError("bad json"),
        )
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        with pytest.raises(OAuthError, match="No access_token"):
            await manager._password_flow(credentials)

    @pytest.mark.asyncio
    async def test_password_flow_decrypt_success_and_error(self, monkeypatch):
        manager = OAuthManager(max_retries=1)
        credentials = {
            "client_id": "cid",
            "client_secret": "x" * 60,
            "token_url": "https://auth.example.com/token",
            "username": "user",
            "password": "pass",
        }

        decryptor = MagicMock()
        decryptor.decrypt_secret_async = AsyncMock(return_value="decrypted")
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_encryption_service", lambda _s: decryptor)
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(auth_encryption_secret="secret"))

        response = _make_response(headers={"content-type": "application/x-www-form-urlencoded"}, text="access_token=ok")
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))
        assert await manager._password_flow(credentials) == "ok"

        decryptor.decrypt_secret_async = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(OAuthError, match="No access_token"):
            bad_response = _make_response(headers={"content-type": "application/json"}, text="nope", json_data={})
            client.post = AsyncMock(return_value=bad_response)
            await manager._password_flow(credentials)

    @pytest.mark.asyncio
    async def test_password_flow_http_error_raises(self, monkeypatch):
        manager = OAuthManager(max_retries=1)
        credentials = {"token_url": "https://auth.example.com/token", "username": "user", "password": "pass"}

        response = _make_response(headers={"content-type": "application/json"}, json_data={"access_token": "x"})
        response.raise_for_status.side_effect = httpx.HTTPError("bad")
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        with pytest.raises(OAuthError, match="Failed to obtain access token"):
            await manager._password_flow(credentials)


class TestOAuthManagerStateStorage:
    @pytest.mark.asyncio
    async def test_store_authorization_state_redis(self, monkeypatch):
        manager = OAuthManager()
        redis = AsyncMock()
        redis.setex = AsyncMock(return_value=True)

        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="redis", redis_url="redis://localhost"))
        monkeypatch.setattr("mcpgateway.services.oauth_manager._get_redis_client", AsyncMock(return_value=redis))

        await manager._store_authorization_state("gw1", "state1", code_verifier="verifier")
        assert redis.setex.called

    @pytest.mark.asyncio
    async def test_store_authorization_state_redis_failure_falls_back(self, monkeypatch):
        import mcpgateway.services.oauth_manager as om

        manager = OAuthManager()
        redis = AsyncMock()
        redis.setex = AsyncMock(side_effect=RuntimeError("boom"))

        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="redis", redis_url="redis://localhost"))
        monkeypatch.setattr("mcpgateway.services.oauth_manager._get_redis_client", AsyncMock(return_value=redis))

        om._oauth_states.clear()
        await manager._store_authorization_state("gw2", "state2", code_verifier="verifier")
        assert any(key.startswith("oauth:state:gw2") for key in om._oauth_states)

    @pytest.mark.asyncio
    async def test_store_authorization_state_memory_cleanup(self, monkeypatch):
        import mcpgateway.services.oauth_manager as om

        manager = OAuthManager()
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="memory"))

        # Insert expired state to trigger cleanup
        om._oauth_states.clear()
        expired_key = "oauth:state:gw:expired"
        om._oauth_states[expired_key] = {
            "state": "expired",
            "gateway_id": "gw",
            "code_verifier": None,
            "expires_at": "2000-01-01T00:00:00+00:00",
            "used": False,
        }

        await manager._store_authorization_state("gw", "new", code_verifier="v")
        assert expired_key not in om._oauth_states

    @pytest.mark.asyncio
    async def test_validate_authorization_state_redis(self, monkeypatch):
        manager = OAuthManager()
        redis = AsyncMock()
        redis.getdel = AsyncMock(
            return_value=b'{"state":"s","gateway_id":"gw","code_verifier":"v","expires_at":"2099-01-01T00:00:00","used":false}'
        )
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="redis", redis_url="redis://localhost"))
        monkeypatch.setattr("mcpgateway.services.oauth_manager._get_redis_client", AsyncMock(return_value=redis))

        assert await manager._validate_authorization_state("gw", "s") is True

    @pytest.mark.asyncio
    async def test_validate_authorization_state_redis_missing_and_used(self, monkeypatch):
        manager = OAuthManager()
        redis = AsyncMock()
        redis.getdel = AsyncMock(return_value=None)
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="redis", redis_url="redis://localhost"))
        monkeypatch.setattr("mcpgateway.services.oauth_manager._get_redis_client", AsyncMock(return_value=redis))
        assert await manager._validate_authorization_state("gw", "missing") is False

        redis.getdel = AsyncMock(
            return_value=b'{"state":"s","gateway_id":"gw","code_verifier":"v","expires_at":"2099-01-01T00:00:00","used":true}'
        )
        assert await manager._validate_authorization_state("gw", "s") is False

    @pytest.mark.asyncio
    async def test_validate_authorization_state_in_memory_expired(self, monkeypatch):
        import mcpgateway.services.oauth_manager as om

        manager = OAuthManager()
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="memory"))
        om._oauth_states.clear()
        om._oauth_states["oauth:state:gw:expired"] = {
            "state": "expired",
            "gateway_id": "gw",
            "code_verifier": None,
            "expires_at": "2000-01-01T00:00:00",
            "used": False,
        }
        assert await manager._validate_authorization_state("gw", "expired") is False

    @pytest.mark.asyncio
    async def test_validate_and_retrieve_state_redis(self, monkeypatch):
        manager = OAuthManager()
        redis = AsyncMock()
        redis.getdel = AsyncMock(
            return_value=b'{"state":"s","gateway_id":"gw","code_verifier":"v","expires_at":"2099-01-01T00:00:00","used":false}'
        )
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="redis", redis_url="redis://localhost"))
        monkeypatch.setattr("mcpgateway.services.oauth_manager._get_redis_client", AsyncMock(return_value=redis))

        data = await manager._validate_and_retrieve_state("gw", "s")
        assert data["code_verifier"] == "v"

    @pytest.mark.asyncio
    async def test_validate_and_retrieve_state_redis_missing(self, monkeypatch):
        manager = OAuthManager()
        redis = AsyncMock()
        redis.getdel = AsyncMock(return_value=None)
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="redis", redis_url="redis://localhost"))
        monkeypatch.setattr("mcpgateway.services.oauth_manager._get_redis_client", AsyncMock(return_value=redis))
        assert await manager._validate_and_retrieve_state("gw", "missing") is None


class TestOAuthManagerAuthorizationCodeExchange:
    @pytest.mark.asyncio
    async def test_exchange_code_for_token_form_encoded(self, monkeypatch):
        manager = OAuthManager(max_retries=1)
        credentials = {
            "client_id": "cid",
            "client_secret": "secret",
            "token_url": "https://auth.example.com/token",
            "redirect_uri": "https://app.example.com/callback",
        }
        response = _make_response(
            headers={"content-type": "application/x-www-form-urlencoded"},
            text="access_token=code123&token_type=Bearer",
        )
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        token = await manager.exchange_code_for_token(credentials, code="c", state="s")
        assert token == "code123"

    @pytest.mark.asyncio
    async def test_exchange_code_for_token_json_parse_error(self, monkeypatch):
        manager = OAuthManager(max_retries=1)
        credentials = {
            "client_id": "cid",
            "client_secret": "secret",
            "token_url": "https://auth.example.com/token",
            "redirect_uri": "https://app.example.com/callback",
        }
        response = _make_response(headers={"content-type": "application/json"}, text="nope", json_exc=ValueError("bad"))
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        with pytest.raises(OAuthError, match="No access_token"):
            await manager.exchange_code_for_token(credentials, code="c", state="s")


class TestOAuthManagerRefreshToken:
    @pytest.mark.asyncio
    async def test_refresh_token_success(self, monkeypatch):
        manager = OAuthManager(max_retries=1)
        credentials = {"client_id": "cid", "token_url": "https://auth.example.com/token"}
        response = _make_response(status_code=200, json_data={"access_token": "new"})
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        result = await manager.refresh_token("refresh", credentials)
        assert result["access_token"] == "new"

    @pytest.mark.asyncio
    async def test_refresh_token_invalid_request(self):
        manager = OAuthManager()
        with pytest.raises(OAuthError, match="No refresh token available"):
            await manager.refresh_token("", {"client_id": "cid", "token_url": "https://auth.example.com/token"})

        with pytest.raises(OAuthError, match="No token URL configured"):
            await manager.refresh_token("refresh", {"client_id": "cid"})

        with pytest.raises(OAuthError, match="No client_id configured"):
            await manager.refresh_token("refresh", {"token_url": "https://auth.example.com/token"})

    @pytest.mark.asyncio
    async def test_refresh_token_invalid_status(self, monkeypatch):
        manager = OAuthManager(max_retries=1)
        credentials = {"client_id": "cid", "token_url": "https://auth.example.com/token"}
        response = _make_response(status_code=400, text="bad")
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        with pytest.raises(OAuthError, match="Refresh token invalid or expired"):
            await manager.refresh_token("refresh", credentials)

    @pytest.mark.asyncio
    async def test_refresh_token_resource_list_and_http_error(self, monkeypatch):
        manager = OAuthManager(max_retries=1)
        credentials = {"client_id": "cid", "token_url": "https://auth.example.com/token", "resource": ["https://api1", "https://api2"]}

        response = _make_response(status_code=500, text="oops")
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        with pytest.raises(OAuthError, match="Failed to refresh token"):
            await manager.refresh_token("refresh", credentials)

        call_data = client.post.call_args[1]["data"]
        assert isinstance(call_data, list)

        client.post = AsyncMock(side_effect=httpx.HTTPError("boom"))
        with pytest.raises(OAuthError, match="Failed to refresh token"):
            await manager.refresh_token("refresh", credentials)


# ============================================================================
# Coverage improvement tests
# ============================================================================


class TestGetRedisClientNonRedis:
    """Cover _get_redis_client when cache_type is not redis (line 74, branch 68->76)."""

    @pytest.mark.asyncio
    async def test_non_redis_cache_type(self, monkeypatch):
        import mcpgateway.services.oauth_manager as om

        monkeypatch.setattr(om, "_REDIS_INITIALIZED", False)
        monkeypatch.setattr(om, "_redis_client", "stale")
        monkeypatch.setattr(om, "get_settings", lambda: SimpleNamespace(cache_type="memory", redis_url=None))

        client = await om._get_redis_client()
        assert client is None
        assert om._REDIS_INITIALIZED is True

    @pytest.mark.asyncio
    async def test_redis_returns_none_client(self, monkeypatch):
        """Redis factory returns None (line 68->76 partial: client is None)."""
        import mcpgateway.services.oauth_manager as om

        monkeypatch.setattr(om, "_REDIS_INITIALIZED", False)
        monkeypatch.setattr(om, "_redis_client", None)
        monkeypatch.setattr(om, "get_settings", lambda: SimpleNamespace(cache_type="redis", redis_url="redis://localhost"))
        monkeypatch.setattr(om, "_get_shared_redis_client", AsyncMock(return_value=None))

        client = await om._get_redis_client()
        assert client is None
        assert om._REDIS_INITIALIZED is True


class TestPasswordFlowFinalFallback:
    """Cover _password_flow final fallback error (lines 389-392)."""

    @pytest.mark.asyncio
    async def test_zero_retries(self):
        manager = OAuthManager(max_retries=0)
        credentials = {"token_url": "https://auth.example.com/token", "username": "user", "password": "pass"}

        with pytest.raises(OAuthError, match="Failed to obtain access token after all retry attempts"):
            await manager._password_flow(credentials)


class TestPasswordFlowHTTPErrorRetry:
    """Cover _password_flow httpx.HTTPError with sleep (line 389)."""

    @pytest.mark.asyncio
    async def test_http_error_retry_then_success(self, monkeypatch):
        manager = OAuthManager(max_retries=2)
        credentials = {"token_url": "https://auth.example.com/token", "username": "user", "password": "pass"}

        success_response = _make_response(headers={"content-type": "application/json"}, json_data={"access_token": "ok"})
        client = AsyncMock()
        client.post = AsyncMock(side_effect=[httpx.HTTPError("fail"), success_response])
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        with patch("asyncio.sleep") as mock_sleep:
            token = await manager._password_flow(credentials)
            assert token == "ok"
            mock_sleep.assert_called_once_with(1)  # 2**0 = 1


class TestExchangeCodeForTokenDecrypt:
    """Cover exchange_code_for_token encrypted secret decryption (branch 460->464)."""

    @pytest.mark.asyncio
    async def test_decrypt_long_secret(self, monkeypatch):
        manager = OAuthManager(max_retries=1)
        long_secret = "x" * 60
        credentials = {
            "client_id": "cid",
            "client_secret": long_secret,
            "token_url": "https://auth.example.com/token",
            "redirect_uri": "https://app.example.com/callback",
        }

        decryptor = MagicMock()
        decryptor.decrypt_secret_async = AsyncMock(return_value="decrypted")
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_encryption_service", lambda _s: decryptor)
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(auth_encryption_secret="secret"))

        response = _make_response(json_data={"access_token": "tok"}, headers={"content-type": "application/json"})
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        token = await manager.exchange_code_for_token(credentials, code="c", state="s")
        assert token == "tok"

    @pytest.mark.asyncio
    async def test_decrypt_returns_none(self, monkeypatch):
        manager = OAuthManager(max_retries=1)
        long_secret = "x" * 60
        credentials = {
            "client_id": "cid",
            "client_secret": long_secret,
            "token_url": "https://auth.example.com/token",
            "redirect_uri": "https://app.example.com/callback",
        }

        decryptor = MagicMock()
        decryptor.decrypt_secret_async = AsyncMock(return_value=None)
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_encryption_service", lambda _s: decryptor)
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(auth_encryption_secret="secret"))

        response = _make_response(json_data={"access_token": "tok"}, headers={"content-type": "application/json"})
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        token = await manager.exchange_code_for_token(credentials, code="c", state="s")
        assert token == "tok"

    @pytest.mark.asyncio
    async def test_decrypt_exception(self, monkeypatch):
        manager = OAuthManager(max_retries=1)
        long_secret = "x" * 60
        credentials = {
            "client_id": "cid",
            "client_secret": long_secret,
            "token_url": "https://auth.example.com/token",
            "redirect_uri": "https://app.example.com/callback",
        }

        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_encryption_service", MagicMock(side_effect=RuntimeError("boom")))
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(auth_encryption_secret="secret"))

        response = _make_response(json_data={"access_token": "tok"}, headers={"content-type": "application/json"})
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        token = await manager.exchange_code_for_token(credentials, code="c", state="s")
        assert token == "tok"


class TestExchangeCodeFinalFallback:
    """Cover exchange_code_for_token final fallback (line 503)."""

    @pytest.mark.asyncio
    async def test_zero_retries(self):
        manager = OAuthManager(max_retries=0)
        credentials = {"client_id": "cid", "client_secret": "secret", "token_url": "https://auth.example.com/token", "redirect_uri": "https://app.example.com/callback"}

        with pytest.raises(OAuthError, match="Failed to exchange code for token after all retry attempts"):
            await manager.exchange_code_for_token(credentials, code="c", state="s")

    @pytest.mark.asyncio
    async def test_http_error_retries(self, monkeypatch):
        manager = OAuthManager(max_retries=1)
        credentials = {"client_id": "cid", "client_secret": "secret", "token_url": "https://auth.example.com/token", "redirect_uri": "https://app.example.com/callback"}

        response = _make_response(headers={"content-type": "application/json"}, json_data={"access_token": "x"})
        response.raise_for_status.side_effect = httpx.HTTPError("bad")
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        with pytest.raises(OAuthError, match="Failed to exchange code for token after 1 attempts"):
            await manager.exchange_code_for_token(credentials, code="c", state="s")


class TestInitiateFlowNoStorage:
    """Cover initiate_authorization_code_flow without token_storage (branch 524->528)."""

    @pytest.mark.asyncio
    async def test_no_token_storage_skips_store(self):
        from pydantic import SecretStr

        with patch("mcpgateway.services.oauth_manager.get_settings") as mock_get_settings:
            mock_settings = MagicMock()
            mock_settings.auth_encryption_secret = SecretStr("test-secret-key")
            mock_get_settings.return_value = mock_settings

            manager = OAuthManager(token_storage=None)
            credentials = {"client_id": "cid", "authorization_url": "https://auth.example.com/authorize", "redirect_uri": "https://app.example.com/callback", "scopes": ["read"]}

            result = await manager.initiate_authorization_code_flow("gw1", credentials, app_user_email="user@example.com")
            assert "authorization_url" in result
            assert "state" in result
            assert result["gateway_id"] == "gw1"


class TestCompleteFlowHMACBranches:
    """Cover HMAC verification branches in complete_authorization_code_flow."""

    @pytest.mark.asyncio
    async def test_invalid_hmac_signature_falls_back(self):
        """Invalid HMAC triggers fallback to legacy format (line 570 via except)."""
        import base64

        from pydantic import SecretStr

        with patch("mcpgateway.services.oauth_manager.get_settings") as mock_settings:
            settings = MagicMock()
            settings.auth_encryption_secret = SecretStr("test-secret")
            settings.oauth_default_timeout = 3600
            mock_settings.return_value = settings

            manager = OAuthManager(token_storage=None)

            # Create state with wrong HMAC signature
            state_bytes = b'{"gateway_id":"gw1","app_user_email":"user@test.com"}'
            bad_signature = b"\x00" * 32
            state = base64.urlsafe_b64encode(state_bytes + bad_signature).decode()

            with patch.object(manager, "_validate_and_retrieve_state", return_value={"code_verifier": "v"}), patch.object(manager, "_exchange_code_for_tokens", return_value={"access_token": "tok"}), patch.object(manager, "_extract_user_id", return_value="user1"):
                result = await manager.complete_authorization_code_flow("gw1", "code", state, {"client_id": "cid"})
                assert result["success"] is True

    @pytest.mark.asyncio
    async def test_gateway_mismatch_falls_back(self):
        """Gateway mismatch triggers OAuthError caught in except (line 580)."""
        import base64
        import hashlib
        import hmac as hmac_mod

        from pydantic import SecretStr

        with patch("mcpgateway.services.oauth_manager.get_settings") as mock_settings:
            settings = MagicMock()
            settings.auth_encryption_secret = SecretStr("test-secret")
            settings.oauth_default_timeout = 3600
            mock_settings.return_value = settings

            manager = OAuthManager(token_storage=None)

            # Create valid HMAC state but with different gateway_id
            import orjson

            state_data = {"gateway_id": "other_gw", "app_user_email": "user@test.com", "nonce": "abc", "timestamp": "2025-01-01T00:00:00"}
            state_bytes = orjson.dumps(state_data)
            secret_key = b"test-secret"
            sig = hmac_mod.new(secret_key, state_bytes, hashlib.sha256).digest()
            state = base64.urlsafe_b64encode(state_bytes + sig).decode()

            with patch.object(manager, "_validate_and_retrieve_state", return_value={"code_verifier": "v"}), patch.object(manager, "_exchange_code_for_tokens", return_value={"access_token": "tok"}), patch.object(manager, "_extract_user_id", return_value="user1"):
                # Gateway mismatch raises OAuthError which is caught in the except block,
                # so app_user_email becomes None, but no token_storage so it proceeds
                result = await manager.complete_authorization_code_flow("gw1", "code", state, {"client_id": "cid"})
                assert result["success"] is True

    @pytest.mark.asyncio
    async def test_no_email_with_storage_raises(self):
        """Token storage present but no email raises OAuthError (line 595)."""
        import base64

        from pydantic import SecretStr

        with patch("mcpgateway.services.oauth_manager.get_settings") as mock_settings:
            settings = MagicMock()
            settings.auth_encryption_secret = SecretStr("test-secret")
            mock_settings.return_value = settings

            mock_storage = MagicMock()
            manager = OAuthManager(token_storage=mock_storage)

            # Create invalid state that triggers fallback → app_user_email = None
            state = base64.urlsafe_b64encode(b"invalid_data_for_parsing").decode()

            with patch.object(manager, "_validate_and_retrieve_state", return_value={"code_verifier": "v"}), patch.object(manager, "_exchange_code_for_tokens", return_value={"access_token": "tok"}), patch.object(manager, "_extract_user_id", return_value="user1"):
                with pytest.raises(OAuthError, match="User context required"):
                    await manager.complete_authorization_code_flow("gw1", "code", state, {"client_id": "cid"})


class _MockColumn:
    """Mock SQLAlchemy column that supports comparison operators."""

    def __lt__(self, other):
        return MagicMock()

    def __eq__(self, other):
        return MagicMock()

    def __hash__(self):
        return id(self)


class TestStoreStateDatabasePath:
    """Cover _store_authorization_state database path (lines 688-692)."""

    @pytest.mark.asyncio
    async def test_database_storage_success(self, monkeypatch):
        manager = OAuthManager()
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="database"))

        mock_db = MagicMock()
        mock_db_gen = MagicMock()
        mock_db_gen.__next__ = MagicMock(return_value=mock_db)
        mock_db_gen.close = MagicMock()

        mock_oauth_state_cls = MagicMock()
        mock_oauth_state_cls.expires_at = _MockColumn()

        mock_db_module = MagicMock()
        mock_db_module.get_db = MagicMock(return_value=mock_db_gen)
        mock_db_module.OAuthState = mock_oauth_state_cls

        with patch.dict("sys.modules", {"mcpgateway.db": mock_db_module}):
            await manager._store_authorization_state("gw1", "state1", code_verifier="v1")

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_database_storage_failure_falls_back(self, monkeypatch):
        import mcpgateway.services.oauth_manager as om

        manager = OAuthManager()
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="database"))

        mock_db_module = MagicMock()
        mock_db_module.get_db = MagicMock(side_effect=RuntimeError("db fail"))
        mock_db_module.OAuthState = MagicMock()

        with patch.dict("sys.modules", {"mcpgateway.db": mock_db_module}):
            om._oauth_states.clear()
            await manager._store_authorization_state("gw1", "state1", code_verifier="v1")

        # Should fall back to in-memory
        assert any(key.startswith("oauth:state:gw1") for key in om._oauth_states)


class TestValidateAuthorizationStateRedisEdgeCases:
    """Cover _validate_authorization_state Redis edge cases."""

    @pytest.mark.asyncio
    async def test_redis_datetime_fallback_parse(self, monkeypatch):
        """Datetime fromisoformat fails, fallback to strptime (lines 743-745)."""
        import orjson

        manager = OAuthManager()
        redis = AsyncMock()
        # Use a datetime format that fromisoformat can't parse but strptime can
        state_data = {"state": "s", "gateway_id": "gw", "code_verifier": "v", "expires_at": "2099-01-01T00:00:00", "used": False}
        # This should work with fromisoformat, so use something that doesn't
        bad_state = {"state": "s", "gateway_id": "gw", "code_verifier": "v", "expires_at": "not-a-date", "used": False}
        redis.getdel = AsyncMock(return_value=orjson.dumps(bad_state))

        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="redis", redis_url="redis://localhost"))
        monkeypatch.setattr("mcpgateway.services.oauth_manager._get_redis_client", AsyncMock(return_value=redis))

        # Both datetime parsers will fail, triggering exception handler (lines 763-764)
        assert await manager._validate_authorization_state("gw", "s") is False

    @pytest.mark.asyncio
    async def test_redis_expired_state(self, monkeypatch):
        """Expired state in Redis (lines 753-754)."""
        import orjson

        manager = OAuthManager()
        redis = AsyncMock()
        state_data = {"state": "s", "gateway_id": "gw", "code_verifier": "v", "expires_at": "2000-01-01T00:00:00+00:00", "used": False}
        redis.getdel = AsyncMock(return_value=orjson.dumps(state_data))

        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="redis", redis_url="redis://localhost"))
        monkeypatch.setattr("mcpgateway.services.oauth_manager._get_redis_client", AsyncMock(return_value=redis))

        assert await manager._validate_authorization_state("gw", "s") is False

    @pytest.mark.asyncio
    async def test_redis_naive_datetime(self, monkeypatch):
        """Naive datetime in Redis requires UTC assumption (branch 747->752)."""
        import orjson

        manager = OAuthManager()
        redis = AsyncMock()
        # Naive datetime (no timezone info)
        state_data = {"state": "s", "gateway_id": "gw", "code_verifier": "v", "expires_at": "2099-01-01T00:00:00", "used": False}
        redis.getdel = AsyncMock(return_value=orjson.dumps(state_data))

        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="redis", redis_url="redis://localhost"))
        monkeypatch.setattr("mcpgateway.services.oauth_manager._get_redis_client", AsyncMock(return_value=redis))

        assert await manager._validate_authorization_state("gw", "s") is True

    @pytest.mark.asyncio
    async def test_redis_exception_falls_back_to_memory(self, monkeypatch):
        """Redis exception falls back (lines 763-764)."""
        import mcpgateway.services.oauth_manager as om

        manager = OAuthManager()
        redis = AsyncMock()
        redis.getdel = AsyncMock(side_effect=RuntimeError("redis error"))

        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="redis", redis_url="redis://localhost"))
        monkeypatch.setattr("mcpgateway.services.oauth_manager._get_redis_client", AsyncMock(return_value=redis))

        # Falls back to memory, state not found
        om._oauth_states.clear()
        assert await manager._validate_authorization_state("gw", "s") is False


class TestValidateAuthorizationStateDatabasePath:
    """Cover _validate_authorization_state database path (lines 778-803)."""

    @pytest.mark.asyncio
    async def test_database_valid_state(self, monkeypatch):
        from datetime import datetime, timezone

        manager = OAuthManager()
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="database"))

        mock_state = MagicMock()
        mock_state.expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
        mock_state.used = False

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_state
        mock_db_gen = MagicMock()
        mock_db_gen.__next__ = MagicMock(return_value=mock_db)
        mock_db_gen.close = MagicMock()

        with patch("mcpgateway.db.get_db", return_value=mock_db_gen), patch("mcpgateway.db.OAuthState", MagicMock()):
            assert await manager._validate_authorization_state("gw", "s") is True
            mock_db.delete.assert_called_once_with(mock_state)
            mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_database_not_found(self, monkeypatch):
        manager = OAuthManager()
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="database"))

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db_gen = MagicMock()
        mock_db_gen.__next__ = MagicMock(return_value=mock_db)
        mock_db_gen.close = MagicMock()

        with patch("mcpgateway.db.get_db", return_value=mock_db_gen), patch("mcpgateway.db.OAuthState", MagicMock()):
            assert await manager._validate_authorization_state("gw", "s") is False

    @pytest.mark.asyncio
    async def test_database_expired_state(self, monkeypatch):
        from datetime import datetime, timezone

        manager = OAuthManager()
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="database"))

        mock_state = MagicMock()
        mock_state.expires_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
        mock_state.used = False

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_state
        mock_db_gen = MagicMock()
        mock_db_gen.__next__ = MagicMock(return_value=mock_db)
        mock_db_gen.close = MagicMock()

        with patch("mcpgateway.db.get_db", return_value=mock_db_gen), patch("mcpgateway.db.OAuthState", MagicMock()):
            assert await manager._validate_authorization_state("gw", "s") is False
            mock_db.delete.assert_called_once_with(mock_state)

    @pytest.mark.asyncio
    async def test_database_used_state(self, monkeypatch):
        from datetime import datetime, timezone

        manager = OAuthManager()
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="database"))

        mock_state = MagicMock()
        mock_state.expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
        mock_state.used = True

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_state
        mock_db_gen = MagicMock()
        mock_db_gen.__next__ = MagicMock(return_value=mock_db)
        mock_db_gen.close = MagicMock()

        with patch("mcpgateway.db.get_db", return_value=mock_db_gen), patch("mcpgateway.db.OAuthState", MagicMock()):
            assert await manager._validate_authorization_state("gw", "s") is False

    @pytest.mark.asyncio
    async def test_database_naive_datetime(self, monkeypatch):
        from datetime import datetime

        manager = OAuthManager()
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="database"))

        mock_state = MagicMock()
        mock_state.expires_at = datetime(2099, 1, 1)  # Naive datetime
        mock_state.used = False

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_state
        mock_db_gen = MagicMock()
        mock_db_gen.__next__ = MagicMock(return_value=mock_db)
        mock_db_gen.close = MagicMock()

        with patch("mcpgateway.db.get_db", return_value=mock_db_gen), patch("mcpgateway.db.OAuthState", MagicMock()):
            assert await manager._validate_authorization_state("gw", "s") is True

    @pytest.mark.asyncio
    async def test_database_exception_falls_back(self, monkeypatch):
        import mcpgateway.services.oauth_manager as om

        manager = OAuthManager()
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="database"))

        with patch("mcpgateway.db.get_db", side_effect=RuntimeError("db error")), patch("mcpgateway.db.OAuthState", MagicMock()):
            om._oauth_states.clear()
            assert await manager._validate_authorization_state("gw", "s") is False


class TestValidateAuthorizationStateMemoryUsed:
    """Cover in-memory used state (lines 831-832)."""

    @pytest.mark.asyncio
    async def test_memory_used_state(self, monkeypatch):
        import mcpgateway.services.oauth_manager as om

        manager = OAuthManager()
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="memory"))

        om._oauth_states.clear()
        om._oauth_states["oauth:state:gw:used"] = {
            "state": "used",
            "gateway_id": "gw",
            "code_verifier": None,
            "expires_at": "2099-01-01T00:00:00+00:00",
            "used": True,
        }
        assert await manager._validate_authorization_state("gw", "used") is False


class TestValidateAndRetrieveStateRedisEdgeCases:
    """Cover _validate_and_retrieve_state Redis edge cases."""

    @pytest.mark.asyncio
    async def test_redis_datetime_fallback(self, monkeypatch):
        """Fallback datetime parse (lines 866-867)."""
        import orjson

        manager = OAuthManager()
        redis = AsyncMock()
        # Use format that needs strptime fallback
        bad_state = {"state": "s", "gateway_id": "gw", "code_verifier": "v", "expires_at": "bad-date", "used": False}
        redis.getdel = AsyncMock(return_value=orjson.dumps(bad_state))

        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="redis", redis_url="redis://localhost"))
        monkeypatch.setattr("mcpgateway.services.oauth_manager._get_redis_client", AsyncMock(return_value=redis))

        # Both parsers fail → exception → None (falls back)
        result = await manager._validate_and_retrieve_state("gw", "s")
        # Falls back to in-memory (no state there) → None
        assert result is None

    @pytest.mark.asyncio
    async def test_redis_expired(self, monkeypatch):
        """Expired state returns None (line 873)."""
        import orjson

        manager = OAuthManager()
        redis = AsyncMock()
        state_data = {"state": "s", "gateway_id": "gw", "code_verifier": "v", "expires_at": "2000-01-01T00:00:00+00:00", "used": False}
        redis.getdel = AsyncMock(return_value=orjson.dumps(state_data))

        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="redis", redis_url="redis://localhost"))
        monkeypatch.setattr("mcpgateway.services.oauth_manager._get_redis_client", AsyncMock(return_value=redis))

        assert await manager._validate_and_retrieve_state("gw", "s") is None

    @pytest.mark.asyncio
    async def test_redis_naive_datetime(self, monkeypatch):
        """Naive datetime requires UTC assumption (branch 869->872)."""
        import orjson

        manager = OAuthManager()
        redis = AsyncMock()
        state_data = {"state": "s", "gateway_id": "gw", "code_verifier": "v", "expires_at": "2099-01-01T00:00:00", "used": False}
        redis.getdel = AsyncMock(return_value=orjson.dumps(state_data))

        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="redis", redis_url="redis://localhost"))
        monkeypatch.setattr("mcpgateway.services.oauth_manager._get_redis_client", AsyncMock(return_value=redis))

        result = await manager._validate_and_retrieve_state("gw", "s")
        assert result is not None
        assert result["code_verifier"] == "v"

    @pytest.mark.asyncio
    async def test_redis_exception(self, monkeypatch):
        """Redis exception falls back (lines 876-877)."""
        import mcpgateway.services.oauth_manager as om

        manager = OAuthManager()
        redis = AsyncMock()
        redis.getdel = AsyncMock(side_effect=RuntimeError("redis error"))

        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="redis", redis_url="redis://localhost"))
        monkeypatch.setattr("mcpgateway.services.oauth_manager._get_redis_client", AsyncMock(return_value=redis))

        om._oauth_states.clear()
        assert await manager._validate_and_retrieve_state("gw", "s") is None


class TestValidateAndRetrieveStateDatabasePath:
    """Cover _validate_and_retrieve_state database path (lines 890-914)."""

    @pytest.mark.asyncio
    async def test_database_valid(self, monkeypatch):
        from datetime import datetime, timezone

        manager = OAuthManager()
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="database"))

        mock_state = MagicMock()
        mock_state.state = "s"
        mock_state.gateway_id = "gw"
        mock_state.code_verifier = "v"
        mock_state.expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
        mock_state.used = False

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_state
        mock_db_gen = MagicMock()
        mock_db_gen.__next__ = MagicMock(return_value=mock_db)
        mock_db_gen.close = MagicMock()

        with patch("mcpgateway.db.get_db", return_value=mock_db_gen), patch("mcpgateway.db.OAuthState", MagicMock()):
            result = await manager._validate_and_retrieve_state("gw", "s")
            assert result is not None
            assert result["code_verifier"] == "v"
            mock_db.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_database_not_found(self, monkeypatch):
        manager = OAuthManager()
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="database"))

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_db_gen = MagicMock()
        mock_db_gen.__next__ = MagicMock(return_value=mock_db)
        mock_db_gen.close = MagicMock()

        with patch("mcpgateway.db.get_db", return_value=mock_db_gen), patch("mcpgateway.db.OAuthState", MagicMock()):
            assert await manager._validate_and_retrieve_state("gw", "s") is None

    @pytest.mark.asyncio
    async def test_database_expired(self, monkeypatch):
        from datetime import datetime, timezone

        manager = OAuthManager()
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="database"))

        mock_state = MagicMock()
        mock_state.expires_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
        mock_state.used = False

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_state
        mock_db_gen = MagicMock()
        mock_db_gen.__next__ = MagicMock(return_value=mock_db)
        mock_db_gen.close = MagicMock()

        with patch("mcpgateway.db.get_db", return_value=mock_db_gen), patch("mcpgateway.db.OAuthState", MagicMock()):
            assert await manager._validate_and_retrieve_state("gw", "s") is None
            mock_db.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_database_used(self, monkeypatch):
        from datetime import datetime, timezone

        manager = OAuthManager()
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="database"))

        mock_state = MagicMock()
        mock_state.expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
        mock_state.used = True

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_state
        mock_db_gen = MagicMock()
        mock_db_gen.__next__ = MagicMock(return_value=mock_db)
        mock_db_gen.close = MagicMock()

        with patch("mcpgateway.db.get_db", return_value=mock_db_gen), patch("mcpgateway.db.OAuthState", MagicMock()):
            assert await manager._validate_and_retrieve_state("gw", "s") is None

    @pytest.mark.asyncio
    async def test_database_naive_datetime(self, monkeypatch):
        from datetime import datetime

        manager = OAuthManager()
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="database"))

        mock_state = MagicMock()
        mock_state.state = "s"
        mock_state.gateway_id = "gw"
        mock_state.code_verifier = "v"
        mock_state.expires_at = datetime(2099, 1, 1)  # Naive
        mock_state.used = False

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_state
        mock_db_gen = MagicMock()
        mock_db_gen.__next__ = MagicMock(return_value=mock_db)
        mock_db_gen.close = MagicMock()

        with patch("mcpgateway.db.get_db", return_value=mock_db_gen), patch("mcpgateway.db.OAuthState", MagicMock()):
            result = await manager._validate_and_retrieve_state("gw", "s")
            assert result is not None

    @pytest.mark.asyncio
    async def test_database_exception(self, monkeypatch):
        import mcpgateway.services.oauth_manager as om

        manager = OAuthManager()
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="database"))

        with patch("mcpgateway.db.get_db", side_effect=RuntimeError("db error")), patch("mcpgateway.db.OAuthState", MagicMock()):
            om._oauth_states.clear()
            assert await manager._validate_and_retrieve_state("gw", "s") is None


class TestValidateAndRetrieveStateMemoryNaiveDatetime:
    """Cover in-memory naive datetime (line 930)."""

    @pytest.mark.asyncio
    async def test_memory_naive_datetime(self, monkeypatch):
        import mcpgateway.services.oauth_manager as om

        manager = OAuthManager()
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="memory"))

        om._oauth_states.clear()
        om._oauth_states["oauth:state:gw:s"] = {
            "state": "s",
            "gateway_id": "gw",
            "code_verifier": "v",
            "expires_at": "2099-01-01T00:00:00",  # Naive
            "used": False,
        }
        result = await manager._validate_and_retrieve_state("gw", "s")
        assert result is not None
        assert result["code_verifier"] == "v"


class TestCreateAuthUrlWithPKCEResource:
    """Cover _create_authorization_url_with_pkce resource param (lines 987-998)."""

    def test_single_string_resource(self):
        manager = OAuthManager()
        credentials = {"client_id": "cid", "authorization_url": "https://auth.example.com/authorize", "redirect_uri": "https://app.example.com/callback", "scopes": [], "resource": "https://api.example.com"}

        url = manager._create_authorization_url_with_pkce(credentials, "state", "challenge", "S256")
        assert "resource=https" in url

    def test_list_resource(self):
        manager = OAuthManager()
        credentials = {"client_id": "cid", "authorization_url": "https://auth.example.com/authorize", "redirect_uri": "https://app.example.com/callback", "scopes": [], "resource": ["https://api1.example.com", "https://api2.example.com"]}

        url = manager._create_authorization_url_with_pkce(credentials, "state", "challenge", "S256")
        assert "resource=" in url

    def test_no_scopes(self):
        """Test without scopes (branch 987->992 skipped)."""
        manager = OAuthManager()
        credentials = {"client_id": "cid", "authorization_url": "https://auth.example.com/authorize", "redirect_uri": "https://app.example.com/callback"}

        url = manager._create_authorization_url_with_pkce(credentials, "state", "challenge", "S256")
        assert "scope=" not in url

    def test_string_scopes(self):
        """Test with scopes as string (not list)."""
        manager = OAuthManager()
        credentials = {"client_id": "cid", "authorization_url": "https://auth.example.com/authorize", "redirect_uri": "https://app.example.com/callback", "scopes": "read write"}

        url = manager._create_authorization_url_with_pkce(credentials, "state", "challenge", "S256")
        assert "scope=read" in url


class TestExchangeCodeForTokensEdgeCases:
    """Cover _exchange_code_for_tokens edge cases."""

    @pytest.mark.asyncio
    async def test_no_client_secret(self, monkeypatch):
        """Public client without client_secret (branch 1046->1050)."""
        manager = OAuthManager(max_retries=1)
        credentials = {"client_id": "cid", "token_url": "https://auth.example.com/token", "redirect_uri": "https://app.example.com/callback"}

        response = _make_response(json_data={"access_token": "tok"}, headers={"content-type": "application/json"})
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        result = await manager._exchange_code_for_tokens(credentials, "code")
        assert result["access_token"] == "tok"
        # Verify no client_secret in request
        call_data = client.post.call_args[1]["data"]
        assert "client_secret" not in call_data

    @pytest.mark.asyncio
    async def test_single_string_resource(self, monkeypatch):
        """Single string resource param (line 1065)."""
        manager = OAuthManager(max_retries=1)
        credentials = {"client_id": "cid", "client_secret": "secret", "token_url": "https://auth.example.com/token", "redirect_uri": "https://app.example.com/callback", "resource": "https://api.example.com"}

        response = _make_response(json_data={"access_token": "tok"}, headers={"content-type": "application/json"})
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        result = await manager._exchange_code_for_tokens(credentials, "code")
        assert result["access_token"] == "tok"
        call_data = client.post.call_args[1]["data"]
        assert call_data["resource"] == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_resource_list_with_empty(self, monkeypatch):
        """Resource list with falsy entry (branch 1061->1060)."""
        manager = OAuthManager(max_retries=1)
        credentials = {"client_id": "cid", "token_url": "https://auth.example.com/token", "redirect_uri": "https://app.example.com/callback", "resource": ["https://api1.example.com", "", "https://api2.example.com"]}

        response = _make_response(json_data={"access_token": "tok"}, headers={"content-type": "application/json"})
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        result = await manager._exchange_code_for_tokens(credentials, "code")
        assert result["access_token"] == "tok"
        # Only 2 resources should be added (empty string skipped)
        call_data = client.post.call_args[1]["data"]
        resource_entries = [entry for entry in call_data if entry[0] == "resource"]
        assert len(resource_entries) == 2

    @pytest.mark.asyncio
    async def test_json_parse_error(self, monkeypatch):
        """JSON parse fails, fallback to text (branch 1081->1080)."""
        manager = OAuthManager(max_retries=1)
        credentials = {"client_id": "cid", "token_url": "https://auth.example.com/token", "redirect_uri": "https://app.example.com/callback"}

        response = _make_response(headers={"content-type": "application/json"}, text="bad", json_exc=ValueError("bad json"))
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        with pytest.raises(OAuthError, match="No access_token"):
            await manager._exchange_code_for_tokens(credentials, "code")

    @pytest.mark.asyncio
    async def test_final_fallback(self):
        """Zero retries → final fallback (line 1104)."""
        manager = OAuthManager(max_retries=0)
        credentials = {"client_id": "cid", "token_url": "https://auth.example.com/token", "redirect_uri": "https://app.example.com/callback"}

        with pytest.raises(OAuthError, match="Failed to exchange code for token after all retry attempts"):
            await manager._exchange_code_for_tokens(credentials, "code")

    @pytest.mark.asyncio
    async def test_decrypt_long_secret(self, monkeypatch):
        """Decrypt long client_secret in _exchange_code_for_tokens (branch 1024->...)."""
        manager = OAuthManager(max_retries=1)
        long_secret = "x" * 60
        credentials = {"client_id": "cid", "client_secret": long_secret, "token_url": "https://auth.example.com/token", "redirect_uri": "https://app.example.com/callback"}

        decryptor = MagicMock()
        decryptor.decrypt_secret_async = AsyncMock(return_value="decrypted")
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_encryption_service", lambda _s: decryptor)
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(auth_encryption_secret="secret"))

        response = _make_response(json_data={"access_token": "tok"}, headers={"content-type": "application/json"})
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        result = await manager._exchange_code_for_tokens(credentials, "code")
        assert result["access_token"] == "tok"

    @pytest.mark.asyncio
    async def test_form_encoded_response(self, monkeypatch):
        """Form-encoded response handling."""
        manager = OAuthManager(max_retries=1)
        credentials = {"client_id": "cid", "token_url": "https://auth.example.com/token", "redirect_uri": "https://app.example.com/callback"}

        response = _make_response(headers={"content-type": "application/x-www-form-urlencoded"}, text="access_token=tok&token_type=Bearer")
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        result = await manager._exchange_code_for_tokens(credentials, "code")
        assert result["access_token"] == "tok"

    @pytest.mark.asyncio
    async def test_http_error_retry_then_success(self, monkeypatch):
        """HTTPError on first attempt, success on retry triggers sleep (line 1104)."""
        manager = OAuthManager(max_retries=2)
        credentials = {"client_id": "cid", "token_url": "https://auth.example.com/token", "redirect_uri": "https://app.example.com/callback"}

        success_response = _make_response(headers={"content-type": "application/json"}, json_data={"access_token": "tok"})
        client = AsyncMock()
        client.post = AsyncMock(side_effect=[httpx.HTTPError("fail"), success_response])
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        with patch("asyncio.sleep") as mock_sleep:
            result = await manager._exchange_code_for_tokens(credentials, "code")
            assert result["access_token"] == "tok"
            mock_sleep.assert_called_once_with(1)  # 2**0 = 1


class TestRefreshTokenEdgeCases:
    """Cover refresh_token edge cases."""

    @pytest.mark.asyncio
    async def test_single_string_resource(self, monkeypatch):
        """Single string resource in refresh (line 1158)."""
        manager = OAuthManager(max_retries=1)
        credentials = {"client_id": "cid", "token_url": "https://auth.example.com/token", "resource": "https://api.example.com"}

        response = _make_response(status_code=200, json_data={"access_token": "new"})
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        result = await manager.refresh_token("refresh", credentials)
        assert result["access_token"] == "new"
        call_data = client.post.call_args[1]["data"]
        assert call_data["resource"] == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_no_access_token_in_response(self, monkeypatch):
        """Missing access_token in 200 response (line 1170)."""
        manager = OAuthManager(max_retries=1)
        credentials = {"client_id": "cid", "token_url": "https://auth.example.com/token"}

        response = _make_response(status_code=200, json_data={"token_type": "Bearer"})
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        with pytest.raises(OAuthError, match="No access_token in refresh response"):
            await manager.refresh_token("refresh", credentials)

    @pytest.mark.asyncio
    async def test_final_fallback_500_status(self, monkeypatch):
        """500 status through all retries triggers final fallback (line 1187)."""
        manager = OAuthManager(max_retries=1)
        credentials = {"client_id": "cid", "token_url": "https://auth.example.com/token"}

        response = _make_response(status_code=500, text="server error")
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        with pytest.raises(OAuthError, match="Failed to refresh token after all retry attempts"):
            await manager.refresh_token("refresh", credentials)

    @pytest.mark.asyncio
    async def test_http_error_with_retry(self, monkeypatch):
        """HTTPError with retries triggers sleep (line 1185)."""
        manager = OAuthManager(max_retries=2)
        credentials = {"client_id": "cid", "token_url": "https://auth.example.com/token"}

        success_response = _make_response(status_code=200, json_data={"access_token": "new"})
        client = AsyncMock()
        client.post = AsyncMock(side_effect=[httpx.HTTPError("fail"), success_response])
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        with patch("asyncio.sleep") as mock_sleep:
            result = await manager.refresh_token("refresh", credentials)
            assert result["access_token"] == "new"
            mock_sleep.assert_called_once_with(1)  # 2**0 = 1

    @pytest.mark.asyncio
    async def test_resource_list_with_empty(self, monkeypatch):
        """Resource list with falsy entry (branch 1154->1153)."""
        manager = OAuthManager(max_retries=1)
        credentials = {"client_id": "cid", "token_url": "https://auth.example.com/token", "resource": ["https://api1.example.com", "", "https://api2.example.com"]}

        response = _make_response(status_code=200, json_data={"access_token": "new"})
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        result = await manager.refresh_token("refresh", credentials)
        assert result["access_token"] == "new"
        call_data = client.post.call_args[1]["data"]
        resource_entries = [entry for entry in call_data if entry[0] == "resource"]
        assert len(resource_entries) == 2

    @pytest.mark.asyncio
    async def test_no_client_secret(self, monkeypatch):
        """No client_secret in refresh."""
        manager = OAuthManager(max_retries=1)
        credentials = {"client_id": "cid", "token_url": "https://auth.example.com/token"}

        response = _make_response(status_code=200, json_data={"access_token": "new"})
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        result = await manager.refresh_token("refresh", credentials)
        assert result["access_token"] == "new"
        call_data = client.post.call_args[1]["data"]
        assert "client_secret" not in call_data


class TestFormEncodedParseBranches:
    """Cover form-encoded parsing with pair lacking '=' (branches 267->266, 366->365, 477->476, 1081->1080)."""

    @pytest.mark.asyncio
    async def test_client_credentials_form_with_bad_pair(self, monkeypatch):
        """_client_credentials_flow: pair without '=' (branch 267->266)."""
        manager = OAuthManager(max_retries=1)
        credentials = {"client_id": "cid", "client_secret": "secret", "token_url": "https://auth.example.com/token"}

        response = _make_response(headers={"content-type": "application/x-www-form-urlencoded"}, text="access_token=tok&badpair&token_type=Bearer")
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        token = await manager._client_credentials_flow(credentials)
        assert token == "tok"

    @pytest.mark.asyncio
    async def test_password_flow_form_with_bad_pair(self, monkeypatch):
        """_password_flow: pair without '=' (branch 366->365)."""
        manager = OAuthManager(max_retries=1)
        credentials = {"token_url": "https://auth.example.com/token", "username": "user", "password": "pass"}

        response = _make_response(headers={"content-type": "application/x-www-form-urlencoded"}, text="access_token=tok&noequalssign&token_type=Bearer")
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        token = await manager._password_flow(credentials)
        assert token == "tok"

    @pytest.mark.asyncio
    async def test_exchange_code_form_with_bad_pair(self, monkeypatch):
        """exchange_code_for_token: pair without '=' (branch 477->476)."""
        manager = OAuthManager(max_retries=1)
        credentials = {"client_id": "cid", "client_secret": "secret", "token_url": "https://auth.example.com/token", "redirect_uri": "https://app.example.com/callback"}

        response = _make_response(headers={"content-type": "application/x-www-form-urlencoded"}, text="access_token=tok&orphan&token_type=Bearer")
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        token = await manager.exchange_code_for_token(credentials, code="c", state="s")
        assert token == "tok"

    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens_form_with_bad_pair(self, monkeypatch):
        """_exchange_code_for_tokens: pair without '=' (branch 1081->1080)."""
        manager = OAuthManager(max_retries=1)
        credentials = {"client_id": "cid", "token_url": "https://auth.example.com/token", "redirect_uri": "https://app.example.com/callback"}

        response = _make_response(headers={"content-type": "application/x-www-form-urlencoded"}, text="access_token=tok&noeq&token_type=Bearer")
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        result = await manager._exchange_code_for_tokens(credentials, "code")
        assert result["access_token"] == "tok"


class TestExchangeCodeNoClientSecret:
    """Cover exchange_code_for_token without client_secret (branch 460->464)."""

    @pytest.mark.asyncio
    async def test_public_client_no_secret(self, monkeypatch):
        manager = OAuthManager(max_retries=1)
        credentials = {"client_id": "cid", "token_url": "https://auth.example.com/token", "redirect_uri": "https://app.example.com/callback"}

        response = _make_response(json_data={"access_token": "tok"}, headers={"content-type": "application/json"})
        client = AsyncMock()
        client.post = AsyncMock(return_value=response)
        monkeypatch.setattr(manager, "_get_client", AsyncMock(return_value=client))

        token = await manager.exchange_code_for_token(credentials, code="c", state="s")
        assert token == "tok"
        call_data = client.post.call_args[1]["data"]
        assert "client_secret" not in call_data


class TestRedisNoneFallthroughPaths:
    """Cover paths where redis returns None and falls through (branches 664->676, 728->767, 854->880)."""

    @pytest.mark.asyncio
    async def test_store_state_redis_none_falls_to_memory(self, monkeypatch):
        """_store_authorization_state: redis is None, falls through (branch 664->676)."""
        import mcpgateway.services.oauth_manager as om

        manager = OAuthManager()
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="redis", redis_url="redis://localhost"))
        monkeypatch.setattr("mcpgateway.services.oauth_manager._get_redis_client", AsyncMock(return_value=None))

        om._oauth_states.clear()
        await manager._store_authorization_state("gw1", "state1", code_verifier="v1")
        assert any(key.startswith("oauth:state:gw1") for key in om._oauth_states)

    @pytest.mark.asyncio
    async def test_validate_state_redis_none_falls_to_memory(self, monkeypatch):
        """_validate_authorization_state: redis is None, falls through (branch 728->767)."""
        import mcpgateway.services.oauth_manager as om

        manager = OAuthManager()
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="redis", redis_url="redis://localhost"))
        monkeypatch.setattr("mcpgateway.services.oauth_manager._get_redis_client", AsyncMock(return_value=None))

        om._oauth_states.clear()
        assert await manager._validate_authorization_state("gw", "s") is False

    @pytest.mark.asyncio
    async def test_validate_and_retrieve_redis_none_falls_to_memory(self, monkeypatch):
        """_validate_and_retrieve_state: redis is None, falls through (branch 854->880)."""
        import mcpgateway.services.oauth_manager as om

        manager = OAuthManager()
        monkeypatch.setattr("mcpgateway.services.oauth_manager.get_settings", lambda: SimpleNamespace(cache_type="redis", redis_url="redis://localhost"))
        monkeypatch.setattr("mcpgateway.services.oauth_manager._get_redis_client", AsyncMock(return_value=None))

        om._oauth_states.clear()
        assert await manager._validate_and_retrieve_state("gw", "s") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
