# -*- coding: utf-8 -*-
"""Integration tests for DCR (Dynamic Client Registration) flow.

These tests validate the complete DCR flow with PKCE, including:
- Authorization URL generation with PKCE
- State storage and retrieval
- Token exchange with code_verifier
- Client registration with upstream AS
- End-to-end OAuth flows

Tests will FAIL until implementation is complete (TDD Red Phase).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta
from mcpgateway.db import RegisteredOAuthClient, OAuthState, Gateway
from mcpgateway.services.oauth_manager import OAuthManager
from mcpgateway.services.dcr_service import DcrService


@pytest.mark.integration
class TestPKCEFlowIntegration:
    """Integration tests for complete PKCE flow."""

    @pytest.mark.asyncio
    async def test_complete_pkce_flow_with_state_storage(self, test_db):
        """Test complete PKCE flow from initiation to token exchange."""
        from mcpgateway.services.token_storage_service import TokenStorageService
        from mcpgateway.db import OAuthState
        from datetime import datetime, timedelta, timezone
        from unittest.mock import patch

        # Mock get_db() to return the test_db session
        def mock_get_db():
            yield test_db

        with patch("mcpgateway.db.get_db", mock_get_db):
            with patch("mcpgateway.config.get_settings") as mock_settings:
                # Configure settings to use database cache
                mock_settings.return_value.cache_type = "database"

                token_storage = TokenStorageService(test_db)
                oauth_manager = OAuthManager(token_storage=token_storage)

                # Create test gateway
                gateway = Gateway(id="test-gateway-123", name="Test Gateway", slug="test-gateway", description="Test", url="http://localhost:9000/mcp", transport="SSE", capabilities={})
                test_db.add(gateway)
                test_db.commit()

                # Step 1: Generate PKCE parameters and state manually
                pkce_params = oauth_manager._generate_pkce_params()
                credentials = {
                    "client_id": "test-client",
                    "authorization_url": "https://as.example.com/authorize",
                    "token_url": "https://as.example.com/token",
                    "redirect_uri": "http://localhost:4444/callback",
                    "scopes": ["mcp:read", "mcp:tools"],
                }

                state = oauth_manager._generate_state("test-gateway-123", "user@example.com")

                # Manually store state in database for this test
                oauth_state_record = OAuthState(
                    gateway_id="test-gateway-123", state=state, code_verifier=pkce_params["code_verifier"], expires_at=datetime.now(timezone.utc) + timedelta(seconds=600), used=False
                )
                test_db.add(oauth_state_record)
                test_db.commit()

                # Verify state was stored
                oauth_state = test_db.query(OAuthState).filter(OAuthState.gateway_id == "test-gateway-123", OAuthState.state == state).first()

                assert oauth_state is not None
                assert oauth_state.code_verifier is not None
                assert len(oauth_state.code_verifier) >= 43

                # Step 3: Exchange code for token (simulating callback)
                code = "authorization-code-from-as"
                code_verifier = oauth_state.code_verifier

                mock_token_response = {"access_token": "test-access-token", "token_type": "Bearer", "expires_in": 3600}

                with patch("aiohttp.ClientSession") as mock_session_class:
                    # Create mock response
                    mock_response_obj = AsyncMock()
                    mock_response_obj.status = 200
                    mock_response_obj.json = AsyncMock(return_value=mock_token_response)
                    mock_response_obj.raise_for_status = MagicMock()
                    mock_response_obj.headers = {"content-type": "application/json"}

                    # Create mock post that returns the response
                    mock_post = MagicMock(return_value=mock_response_obj)
                    mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_response_obj)
                    mock_post.return_value.__aexit__ = AsyncMock(return_value=None)

                    # Create mock session
                    mock_session = MagicMock()
                    mock_session.post = mock_post
                    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                    mock_session.__aexit__ = AsyncMock(return_value=None)

                    mock_session_class.return_value = mock_session

                    # Complete flow
                    _result = await oauth_manager.complete_authorization_code_flow(gateway_id="test-gateway-123", code=code, state=state, credentials=credentials)  # noqa: F841

                # Verify code_verifier was included in token request
                call_kwargs = mock_post.call_args[1]
                assert call_kwargs["data"]["code_verifier"] == code_verifier

                # Verify state is consumed (single-use)
                oauth_state_after = test_db.query(OAuthState).filter(OAuthState.gateway_id == "test-gateway-123", OAuthState.state == state).first()

                # State should be deleted or marked as used
                assert oauth_state_after is None or oauth_state_after.used is True


@pytest.mark.integration
class TestDCRFlowIntegration:
    """Integration tests for complete DCR flow."""

    @pytest.mark.asyncio
    async def test_complete_dcr_registration_flow(self, test_db):
        """Test complete DCR flow from discovery to token exchange."""
        dcr_service = DcrService()
        oauth_manager = OAuthManager()

        # Create test gateway
        gateway = Gateway(id="test-gw-456", name="DCR Test Gateway", slug="dcr-test-gateway", description="Test DCR", url="http://localhost:9000/mcp", transport="SSE", capabilities={})
        test_db.add(gateway)
        test_db.commit()

        # Mock AS metadata discovery
        mock_metadata = {
            "issuer": "https://as.example.com",
            "authorization_endpoint": "https://as.example.com/authorize",
            "token_endpoint": "https://as.example.com/token",
            "registration_endpoint": "https://as.example.com/register",
            "code_challenge_methods_supported": ["S256"],
        }

        # Mock DCR registration response
        mock_registration = {
            "client_id": "dcr-generated-id-789",
            "client_secret": "dcr-generated-secret-xyz",
            "client_id_issued_at": int(datetime.now(timezone.utc).timestamp()),
            "redirect_uris": ["http://localhost:4444/oauth/callback"],
            "grant_types": ["authorization_code"],
            "token_endpoint_auth_method": "client_secret_basic",
            "registration_client_uri": "https://as.example.com/register/dcr-generated-id-789",
            "registration_access_token": "registration-access-token-abc",
        }

        with patch("aiohttp.ClientSession.get") as mock_get, patch("aiohttp.ClientSession.post") as mock_post:
            # Mock metadata discovery
            mock_get_response = AsyncMock()
            mock_get_response.status = 200
            mock_get_response.json = AsyncMock(return_value=mock_metadata)
            mock_get.return_value.__aenter__.return_value = mock_get_response

            # Mock DCR registration
            mock_post_response = AsyncMock()
            mock_post_response.status = 201
            mock_post_response.json = AsyncMock(return_value=mock_registration)
            mock_post.return_value.__aenter__.return_value = mock_post_response

            # Step 1: Register client via DCR
            registered_client = await dcr_service.register_client(
                gateway_id="test-gw-456",
                gateway_name="DCR Test Gateway",
                issuer="https://as.example.com",
                redirect_uri="http://localhost:4444/oauth/callback",
                scopes=["mcp:read", "mcp:tools"],
                db=test_db,
            )

        # Verify client was registered and stored
        assert registered_client.client_id == "dcr-generated-id-789"
        assert registered_client.issuer == "https://as.example.com"
        assert registered_client.gateway_id == "test-gw-456"
        assert registered_client.is_active is True

        # Verify secret is encrypted (should be long and different from plaintext)
        assert registered_client.client_secret_encrypted != "dcr-generated-secret-xyz"
        assert len(registered_client.client_secret_encrypted) > 50  # Encrypted secrets are long

        # Verify client exists in database
        db_client = test_db.query(RegisteredOAuthClient).filter(RegisteredOAuthClient.gateway_id == "test-gw-456", RegisteredOAuthClient.issuer == "https://as.example.com").first()

        assert db_client is not None
        assert db_client.client_id == "dcr-generated-id-789"

        # Step 2: Use registered client for OAuth flow
        credentials = {
            "client_id": registered_client.client_id,
            "client_secret": registered_client.client_secret_encrypted,
            "authorization_url": mock_metadata["authorization_endpoint"],
            "token_url": mock_metadata["token_endpoint"],
            "redirect_uri": "http://localhost:4444/oauth/callback",
            "scopes": ["mcp:read", "mcp:tools"],
        }

        # Initiate OAuth flow with DCR-registered credentials
        with patch.object(oauth_manager, "token_storage", None):
            result = await oauth_manager.initiate_authorization_code_flow(gateway_id="test-gw-456", credentials=credentials)

        # Verify authorization URL includes PKCE
        assert "code_challenge=" in result["authorization_url"]
        assert f"client_id={registered_client.client_id}" in result["authorization_url"]

    @pytest.mark.asyncio
    async def test_get_or_register_client_reuses_existing(self, test_db):
        """Test that get_or_register_client reuses existing registration."""
        dcr_service = DcrService()

        # Create test gateway
        gateway = Gateway(id="test-gw-reuse", name="Reuse Test", slug="reuse-test", description="Test", url="http://localhost:9000/mcp", transport="SSE", capabilities={})
        test_db.add(gateway)

        # Create existing client
        existing_client = RegisteredOAuthClient(
            id="existing-123",
            gateway_id="test-gw-reuse",
            issuer="https://as.example.com",
            client_id="existing-client-id",
            client_secret_encrypted="gAAAAABencrypted",
            redirect_uris='["http://localhost:4444/callback"]',
            grant_types='["authorization_code"]',
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        test_db.add(existing_client)
        test_db.commit()

        # Call get_or_register_client
        result = await dcr_service.get_or_register_client(
            gateway_id="test-gw-reuse", gateway_name="Reuse Test", issuer="https://as.example.com", redirect_uri="http://localhost:4444/callback", scopes=["mcp:read"], db=test_db
        )

        # Should return existing client
        assert result.id == "existing-123"
        assert result.client_id == "existing-client-id"

        # Should not create a new client
        all_clients = test_db.query(RegisteredOAuthClient).filter(RegisteredOAuthClient.gateway_id == "test-gw-reuse").all()

        assert len(all_clients) == 1


@pytest.mark.integration
class TestPKCESecurityIntegration:
    """Integration tests for PKCE security properties."""

    @pytest.mark.asyncio
    async def test_state_cannot_be_reused(self, test_db):
        """Test that state can only be used once (replay attack prevention)."""
        from mcpgateway.services.token_storage_service import TokenStorageService

        token_storage = TokenStorageService(test_db)
        oauth_manager = OAuthManager(token_storage=token_storage)

        gateway = Gateway(id="test-replay", name="Test", slug="test-replay", description="Test", url="http://localhost:9000/mcp", transport="SSE", capabilities={})
        test_db.add(gateway)
        test_db.commit()

        credentials = {
            "client_id": "test",
            "authorization_url": "https://as.example.com/authorize",
            "token_url": "https://as.example.com/token",
            "redirect_uri": "http://localhost:4444/callback",
            "scopes": ["mcp:read"],
        }

        # Initiate flow and get state
        result = await oauth_manager.initiate_authorization_code_flow(gateway_id="test-replay", credentials=credentials, app_user_email="user@example.com")

        state = result["state"]

        # First attempt should succeed
        state_data = await oauth_manager._validate_and_retrieve_state("test-replay", state)
        assert state_data is not None

        # Second attempt should fail (state consumed)
        state_data2 = await oauth_manager._validate_and_retrieve_state("test-replay", state)
        assert state_data2 is None

    @pytest.mark.asyncio
    async def test_expired_state_is_rejected(self, test_db):
        """Test that expired state is rejected."""
        oauth_manager = OAuthManager()

        # Manually create expired state
        expired_state = OAuthState(
            gateway_id="test-expired",
            state="expired-state-123",
            code_verifier="verifier",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=60),  # Expired
            used=False,
        )
        test_db.add(expired_state)
        test_db.commit()

        # Attempt to validate should fail
        state_data = await oauth_manager._validate_and_retrieve_state("test-expired", "expired-state-123")

        assert state_data is None

    @pytest.mark.asyncio
    async def test_code_verifier_matches_challenge(self, test_db):
        """Test that code_verifier correctly validates against code_challenge."""
        import base64
        import hashlib

        oauth_manager = OAuthManager()

        # Generate PKCE parameters
        pkce = oauth_manager._generate_pkce_params()

        # Manually compute challenge from verifier
        expected_challenge = base64.urlsafe_b64encode(hashlib.sha256(pkce["code_verifier"].encode("utf-8")).digest()).decode("utf-8").rstrip("=")

        # Verify they match
        assert pkce["code_challenge"] == expected_challenge


@pytest.mark.integration
class TestDCRErrorHandling:
    """Integration tests for DCR error handling."""

    @pytest.mark.asyncio
    async def test_dcr_handles_missing_registration_endpoint(self, test_db):
        """Test graceful handling when AS doesn't support DCR."""
        dcr_service = DcrService()

        gateway = Gateway(id="test-no-dcr", name="Test", slug="test-no-dcr", description="Test", url="http://localhost:9000/mcp", transport="SSE", capabilities={})
        test_db.add(gateway)
        test_db.commit()

        # Mock metadata without registration_endpoint
        mock_metadata = {
            "issuer": "https://as-no-dcr.example.com",
            "authorization_endpoint": "https://as-no-dcr.example.com/authorize",
            "token_endpoint": "https://as-no-dcr.example.com/token",
            # No registration_endpoint
        }

        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_metadata)
            mock_get.return_value.__aenter__.return_value = mock_response

            from mcpgateway.services.dcr_service import DcrError

            with pytest.raises(DcrError, match="does not support Dynamic Client Registration"):
                await dcr_service.register_client(
                    gateway_id="test-no-dcr", gateway_name="Test", issuer="https://as-no-dcr.example.com", redirect_uri="http://localhost:4444/callback", scopes=["mcp:read"], db=test_db
                )

    @pytest.mark.asyncio
    async def test_dcr_handles_invalid_issuer(self, test_db):
        """Test validation of issuer in metadata."""
        from mcpgateway.services import dcr_service as dcr_module

        # Clear metadata cache to ensure test isolation
        dcr_module._metadata_cache.clear()

        dcr_service = DcrService()

        # Mock metadata with mismatched issuer
        mock_metadata = {
            "issuer": "https://different-issuer.com",  # Doesn't match request
            "authorization_endpoint": "https://as.example.com/authorize",
        }

        with patch("aiohttp.ClientSession") as mock_session_class:
            # Create mock response
            mock_response_obj = AsyncMock()
            mock_response_obj.status = 200
            mock_response_obj.json = AsyncMock(return_value=mock_metadata)

            # Create mock get that returns the response
            mock_get = MagicMock(return_value=mock_response_obj)
            mock_get.return_value.__aenter__ = AsyncMock(return_value=mock_response_obj)
            mock_get.return_value.__aexit__ = AsyncMock(return_value=None)

            # Create mock session
            mock_session = MagicMock()
            mock_session.get = mock_get
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            mock_session_class.return_value = mock_session

            from mcpgateway.services.dcr_service import DcrError

            with pytest.raises(DcrError, match="issuer mismatch"):
                await dcr_service.discover_as_metadata("https://as.example.com")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "integration"])
