# -*- coding: utf-8 -*-
"""Test DCR Service (RFC 7591 Dynamic Client Registration).

This test suite validates the DCR service implementation following TDD Red Phase.
Tests will FAIL until implementation is complete.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from mcpgateway.services.dcr_service import DcrService, DcrError


class TestDiscoverASMetadata:
    """Test AS metadata discovery (RFC 8414)."""

    @pytest.mark.asyncio
    async def test_discover_as_metadata_success(self):
        """Test successful AS metadata discovery."""
        dcr_service = DcrService()
        
        mock_metadata = {
            "issuer": "https://as.example.com",
            "authorization_endpoint": "https://as.example.com/authorize",
            "token_endpoint": "https://as.example.com/token",
            "registration_endpoint": "https://as.example.com/register",
            "code_challenge_methods_supported": ["S256", "plain"],
            "grant_types_supported": ["authorization_code", "refresh_token"]
        }
        
        with patch('aiohttp.ClientSession.get') as mock_get:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_metadata)
            mock_get.return_value.__aenter__.return_value = mock_response
            
            result = await dcr_service.discover_as_metadata("https://as.example.com")
            
            assert result["issuer"] == "https://as.example.com"
            assert "registration_endpoint" in result
            assert result["registration_endpoint"] == "https://as.example.com/register"

    @pytest.mark.asyncio
    async def test_discover_as_metadata_tries_rfc8414_first(self):
        """Test that RFC 8414 path is tried first."""
        dcr_service = DcrService()
        
        with patch('aiohttp.ClientSession.get') as mock_get:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"issuer": "test"})
            mock_get.return_value.__aenter__.return_value = mock_response
            
            await dcr_service.discover_as_metadata("https://as.example.com")
            
            # First call should be RFC 8414 path
            first_call_url = mock_get.call_args_list[0][0][0]
            assert "/.well-known/oauth-authorization-server" in first_call_url

    @pytest.mark.asyncio
    async def test_discover_as_metadata_falls_back_to_oidc(self):
        """Test fallback to OIDC discovery if RFC 8414 fails."""
        dcr_service = DcrService()
        
        with patch('aiohttp.ClientSession.get') as mock_get:
            # First call (RFC 8414) fails
            mock_response_404 = AsyncMock()
            mock_response_404.status = 404
            
            # Second call (OIDC) succeeds
            mock_response_200 = AsyncMock()
            mock_response_200.status = 200
            mock_response_200.json = AsyncMock(return_value={"issuer": "test"})
            
            mock_get.return_value.__aenter__.side_effect = [
                mock_response_404,
                mock_response_200
            ]
            
            result = await dcr_service.discover_as_metadata("https://as.example.com")
            
            # Should have tried both paths
            assert mock_get.call_count == 2

    @pytest.mark.asyncio
    async def test_discover_as_metadata_not_found(self):
        """Test when metadata endpoints return 404."""
        dcr_service = DcrService()
        
        with patch('aiohttp.ClientSession.get') as mock_get:
            mock_response = AsyncMock()
            mock_response.status = 404
            mock_get.return_value.__aenter__.return_value = mock_response
            
            with pytest.raises(DcrError, match="Metadata not found"):
                await dcr_service.discover_as_metadata("https://as.example.com")

    @pytest.mark.asyncio
    async def test_discover_as_metadata_caches_result(self):
        """Test that metadata is cached to avoid repeated requests."""
        dcr_service = DcrService()
        
        mock_metadata = {"issuer": "https://as.example.com"}
        
        with patch('aiohttp.ClientSession.get') as mock_get:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_metadata)
            mock_get.return_value.__aenter__.return_value = mock_response
            
            # First call
            result1 = await dcr_service.discover_as_metadata("https://as.example.com")
            
            # Second call should use cache
            result2 = await dcr_service.discover_as_metadata("https://as.example.com")
            
            # Should only have called API once
            assert mock_get.call_count == 1
            assert result1 == result2

    @pytest.mark.asyncio
    async def test_discover_as_metadata_validates_issuer(self):
        """Test that discovered metadata validates issuer matches."""
        dcr_service = DcrService()
        
        mock_metadata = {
            "issuer": "https://different-issuer.com",  # Doesn't match
            "authorization_endpoint": "https://as.example.com/authorize"
        }
        
        with patch('aiohttp.ClientSession.get') as mock_get:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_metadata)
            mock_get.return_value.__aenter__.return_value = mock_response
            
            with pytest.raises(DcrError, match="issuer mismatch"):
                await dcr_service.discover_as_metadata("https://as.example.com")


class TestRegisterClient:
    """Test client registration (RFC 7591)."""

    @pytest.mark.asyncio
    async def test_register_client_success(self, test_db):
        """Test successful client registration."""
        dcr_service = DcrService()
        
        mock_metadata = {
            "registration_endpoint": "https://as.example.com/register"
        }
        
        mock_registration_response = {
            "client_id": "dcr-generated-client-123",
            "client_secret": "dcr-generated-secret-xyz",
            "client_id_issued_at": 1234567890,
            "redirect_uris": ["http://localhost:4444/oauth/callback"],
            "grant_types": ["authorization_code"],
            "token_endpoint_auth_method": "client_secret_basic",
            "registration_client_uri": "https://as.example.com/register/dcr-generated-client-123",
            "registration_access_token": "registration-token-abc"
        }
        
        with patch.object(dcr_service, 'discover_as_metadata') as mock_discover, \
             patch('aiohttp.ClientSession.post') as mock_post:
            
            mock_discover.return_value = mock_metadata
            
            mock_response = AsyncMock()
            mock_response.status = 201
            mock_response.json = AsyncMock(return_value=mock_registration_response)
            mock_post.return_value.__aenter__.return_value = mock_response
            
            result = await dcr_service.register_client(
                gateway_id="test-gw-123",
                gateway_name="Test Gateway",
                issuer="https://as.example.com",
                redirect_uri="http://localhost:4444/oauth/callback",
                scopes=["mcp:read", "mcp:tools"],
                db=test_db
            )
            
            assert result.client_id == "dcr-generated-client-123"
            assert result.issuer == "https://as.example.com"
            assert result.gateway_id == "test-gw-123"
            # Secret should be encrypted
            assert result.client_secret_encrypted.startswith("gAAAAAB")

    @pytest.mark.asyncio
    async def test_register_client_builds_correct_request(self, test_db):
        """Test that registration request has correct RFC 7591 fields."""
        dcr_service = DcrService()
        
        mock_metadata = {
            "registration_endpoint": "https://as.example.com/register"
        }
        
        with patch.object(dcr_service, 'discover_as_metadata') as mock_discover, \
             patch('aiohttp.ClientSession.post') as mock_post:
            
            mock_discover.return_value = mock_metadata
            
            mock_response = AsyncMock()
            mock_response.status = 201
            mock_response.json = AsyncMock(return_value={
                "client_id": "test",
                "redirect_uris": []
            })
            mock_post.return_value.__aenter__.return_value = mock_response
            
            await dcr_service.register_client(
                gateway_id="test-gw",
                gateway_name="Test Gateway",
                issuer="https://as.example.com",
                redirect_uri="http://localhost:4444/callback",
                scopes=["mcp:read"],
                db=test_db
            )
            
            # Verify request payload
            call_kwargs = mock_post.call_args[1]
            request_json = call_kwargs["json"]
            
            assert request_json["client_name"] == "MCP Gateway (Test Gateway)"
            assert request_json["redirect_uris"] == ["http://localhost:4444/callback"]
            assert request_json["grant_types"] == ["authorization_code"]
            assert request_json["response_types"] == ["code"]
            assert request_json["scope"] == "mcp:read"

    @pytest.mark.asyncio
    async def test_register_client_no_registration_endpoint(self, test_db):
        """Test registration failure when AS doesn't support DCR."""
        dcr_service = DcrService()
        
        mock_metadata = {
            "issuer": "https://as.example.com",
            # No registration_endpoint
        }
        
        with patch.object(dcr_service, 'discover_as_metadata') as mock_discover:
            mock_discover.return_value = mock_metadata
            
            with pytest.raises(DcrError, match="does not support Dynamic Client Registration"):
                await dcr_service.register_client(
                    gateway_id="test-gw",
                    gateway_name="Test",
                    issuer="https://as.example.com",
                    redirect_uri="http://localhost:4444/callback",
                    scopes=["mcp:read"],
                    db=test_db
                )

    @pytest.mark.asyncio
    async def test_register_client_handles_registration_error(self, test_db):
        """Test handling of registration errors (invalid_redirect_uri, etc.)."""
        dcr_service = DcrService()
        
        mock_metadata = {
            "registration_endpoint": "https://as.example.com/register"
        }
        
        with patch.object(dcr_service, 'discover_as_metadata') as mock_discover, \
             patch('aiohttp.ClientSession.post') as mock_post:
            
            mock_discover.return_value = mock_metadata
            
            mock_response = AsyncMock()
            mock_response.status = 400
            mock_response.json = AsyncMock(return_value={
                "error": "invalid_redirect_uri",
                "error_description": "Redirect URI not allowed"
            })
            mock_post.return_value.__aenter__.return_value = mock_response
            
            with pytest.raises(DcrError, match="invalid_redirect_uri"):
                await dcr_service.register_client(
                    gateway_id="test-gw",
                    gateway_name="Test",
                    issuer="https://as.example.com",
                    redirect_uri="http://invalid",
                    scopes=["mcp:read"],
                    db=test_db
                )

    @pytest.mark.asyncio
    async def test_register_client_stores_encrypted_secret(self, test_db):
        """Test that client_secret is encrypted before storage."""
        dcr_service = DcrService()
        
        mock_metadata = {"registration_endpoint": "https://as.example.com/register"}
        mock_registration = {
            "client_id": "test-client",
            "client_secret": "plaintext-secret",
            "redirect_uris": ["http://localhost:4444/callback"]
        }
        
        with patch.object(dcr_service, 'discover_as_metadata') as mock_discover, \
             patch('aiohttp.ClientSession.post') as mock_post:
            
            mock_discover.return_value = mock_metadata
            mock_response = AsyncMock()
            mock_response.status = 201
            mock_response.json = AsyncMock(return_value=mock_registration)
            mock_post.return_value.__aenter__.return_value = mock_response
            
            result = await dcr_service.register_client(
                gateway_id="test-gw",
                gateway_name="Test",
                issuer="https://as.example.com",
                redirect_uri="http://localhost:4444/callback",
                scopes=["mcp:read"],
                db=test_db
            )
            
            # Secret should NOT be stored as plaintext
            assert result.client_secret_encrypted != "plaintext-secret"
            # Should be Fernet encrypted (starts with gAAAAAB)
            assert result.client_secret_encrypted.startswith("gAAAAAB")


class TestGetOrRegisterClient:
    """Test get-or-create pattern for DCR."""

    @pytest.mark.asyncio
    async def test_get_or_register_client_returns_existing(self, test_db):
        """Test that existing client is returned if found."""
        dcr_service = DcrService()
        
        # Mock existing client in database
        from mcpgateway.db import RegisteredOAuthClient
        
        existing_client = RegisteredOAuthClient(
            id="existing-id",
            gateway_id="test-gw",
            issuer="https://as.example.com",
            client_id="existing-client",
            client_secret_encrypted="encrypted",
            redirect_uris='["http://localhost:4444/callback"]',
            grant_types='["authorization_code"]',
            is_active=True
        )
        test_db.add(existing_client)
        test_db.commit()
        
        result = await dcr_service.get_or_register_client(
            gateway_id="test-gw",
            gateway_name="Test",
            issuer="https://as.example.com",
            redirect_uri="http://localhost:4444/callback",
            scopes=["mcp:read"],
            db=test_db
        )
        
        assert result.id == "existing-id"
        assert result.client_id == "existing-client"

    @pytest.mark.asyncio
    async def test_get_or_register_client_registers_if_not_found(self, test_db):
        """Test that new client is registered if not found."""
        dcr_service = DcrService()
        
        with patch.object(dcr_service, 'register_client') as mock_register:
            from mcpgateway.db import RegisteredOAuthClient
            
            mock_register.return_value = RegisteredOAuthClient(
                id="new-id",
                gateway_id="test-gw",
                issuer="https://as.example.com",
                client_id="new-client",
                client_secret_encrypted="encrypted",
                redirect_uris='[]',
                grant_types='[]'
            )
            
            result = await dcr_service.get_or_register_client(
                gateway_id="test-gw",
                gateway_name="Test",
                issuer="https://as.example.com",
                redirect_uri="http://localhost:4444/callback",
                scopes=["mcp:read"],
                db=test_db
            )
            
            mock_register.assert_called_once()
            assert result.client_id == "new-client"

    @pytest.mark.asyncio
    async def test_get_or_register_client_respects_auto_register_flag(self, test_db):
        """Test that auto-register flag is respected."""
        dcr_service = DcrService()
        
        from mcpgateway.config import get_settings
        
        with patch.object(get_settings(), 'dcr_auto_register_on_missing_credentials', False):
            with pytest.raises(DcrError, match="auto-register is disabled"):
                await dcr_service.get_or_register_client(
                    gateway_id="test-gw",
                    gateway_name="Test",
                    issuer="https://as.example.com",
                    redirect_uri="http://localhost:4444/callback",
                    scopes=["mcp:read"],
                    db=test_db
                )


class TestUpdateClientRegistration:
    """Test updating client registration (RFC 7591 section 4.2)."""

    @pytest.mark.asyncio
    async def test_update_client_registration_success(self, test_db):
        """Test successful client registration update."""
        dcr_service = DcrService()
        
        from mcpgateway.db import RegisteredOAuthClient
        
        client_record = RegisteredOAuthClient(
            id="client-id",
            gateway_id="test-gw",
            issuer="https://as.example.com",
            client_id="test-client",
            client_secret_encrypted="encrypted",
            registration_client_uri="https://as.example.com/register/test-client",
            registration_access_token_encrypted="encrypted-token",
            redirect_uris='["http://localhost:4444/callback"]',
            grant_types='["authorization_code"]'
        )
        
        mock_response = {
            "client_id": "test-client",
            "client_secret": "updated-secret",
            "redirect_uris": ["http://localhost:4444/callback", "http://localhost:4444/callback2"]
        }
        
        with patch('aiohttp.ClientSession.put') as mock_put:
            mock_response_obj = AsyncMock()
            mock_response_obj.status = 200
            mock_response_obj.json = AsyncMock(return_value=mock_response)
            mock_put.return_value.__aenter__.return_value = mock_response_obj
            
            result = await dcr_service.update_client_registration(client_record, test_db)
            
            assert result.client_id == "test-client"

    @pytest.mark.asyncio
    async def test_update_client_registration_uses_access_token(self, test_db):
        """Test that update uses registration_access_token."""
        dcr_service = DcrService()
        
        from mcpgateway.db import RegisteredOAuthClient
        
        client_record = RegisteredOAuthClient(
            id="client-id",
            gateway_id="test-gw",
            issuer="https://as.example.com",
            client_id="test-client",
            client_secret_encrypted="encrypted",
            registration_client_uri="https://as.example.com/register/test-client",
            registration_access_token_encrypted="encrypted-token",
            redirect_uris='[]',
            grant_types='[]'
        )
        
        with patch('aiohttp.ClientSession.put') as mock_put:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"client_id": "test"})
            mock_put.return_value.__aenter__.return_value = mock_response
            
            await dcr_service.update_client_registration(client_record, test_db)
            
            # Verify Bearer token was used
            call_kwargs = mock_put.call_args[1]
            assert "Authorization" in call_kwargs["headers"]
            assert call_kwargs["headers"]["Authorization"].startswith("Bearer ")


class TestDeleteClientRegistration:
    """Test deleting/revoking client registration (RFC 7591 section 4.3)."""

    @pytest.mark.asyncio
    async def test_delete_client_registration_success(self, test_db):
        """Test successful client deletion."""
        dcr_service = DcrService()
        
        from mcpgateway.db import RegisteredOAuthClient
        
        client_record = RegisteredOAuthClient(
            id="client-id",
            gateway_id="test-gw",
            issuer="https://as.example.com",
            client_id="test-client",
            client_secret_encrypted="encrypted",
            registration_client_uri="https://as.example.com/register/test-client",
            registration_access_token_encrypted="encrypted-token",
            redirect_uris='[]',
            grant_types='[]'
        )
        
        with patch('aiohttp.ClientSession.delete') as mock_delete:
            mock_response = AsyncMock()
            mock_response.status = 204
            mock_delete.return_value.__aenter__.return_value = mock_response
            
            result = await dcr_service.delete_client_registration(client_record, test_db)
            
            assert result is True

    @pytest.mark.asyncio
    async def test_delete_client_registration_handles_404(self, test_db):
        """Test that 404 (already deleted) is handled gracefully."""
        dcr_service = DcrService()
        
        from mcpgateway.db import RegisteredOAuthClient
        
        client_record = RegisteredOAuthClient(
            id="client-id",
            gateway_id="test-gw",
            issuer="https://as.example.com",
            client_id="test-client",
            client_secret_encrypted="encrypted",
            registration_client_uri="https://as.example.com/register/test-client",
            registration_access_token_encrypted="encrypted-token",
            redirect_uris='[]',
            grant_types='[]'
        )
        
        with patch('aiohttp.ClientSession.delete') as mock_delete:
            mock_response = AsyncMock()
            mock_response.status = 404
            mock_delete.return_value.__aenter__.return_value = mock_response
            
            # Should still return True (client is gone)
            result = await dcr_service.delete_client_registration(client_record, test_db)
            
            assert result is True


class TestIssuerValidation:
    """Test issuer allowlist validation."""

    @pytest.mark.asyncio
    async def test_issuer_validation_allows_when_list_empty(self, test_db):
        """Test that empty allowlist allows all issuers."""
        dcr_service = DcrService()
        
        from mcpgateway.config import get_settings
        
        with patch.object(get_settings(), 'dcr_allowed_issuers', []):
            # Should not raise error
            pass  # Validation happens in register_client

    @pytest.mark.asyncio
    async def test_issuer_validation_blocks_unauthorized(self, test_db):
        """Test that unauthorized issuer is blocked."""
        dcr_service = DcrService()
        
        from mcpgateway.config import get_settings
        
        with patch.object(get_settings(), 'dcr_allowed_issuers', ["https://trusted.com"]):
            with pytest.raises(DcrError, match="not in allowed issuers"):
                await dcr_service.register_client(
                    gateway_id="test-gw",
                    gateway_name="Test",
                    issuer="https://untrusted.com",  # Not in allowlist
                    redirect_uri="http://localhost:4444/callback",
                    scopes=["mcp:read"],
                    db=test_db
                )

    @pytest.mark.asyncio
    async def test_issuer_validation_allows_authorized(self, test_db):
        """Test that authorized issuer is allowed."""
        dcr_service = DcrService()
        
        from mcpgateway.config import get_settings
        
        with patch.object(get_settings(), 'dcr_allowed_issuers', ["https://as.example.com"]), \
             patch.object(dcr_service, 'discover_as_metadata') as mock_discover, \
             patch('aiohttp.ClientSession.post') as mock_post:
            
            mock_discover.return_value = {"registration_endpoint": "https://as.example.com/register"}
            mock_response = AsyncMock()
            mock_response.status = 201
            mock_response.json = AsyncMock(return_value={
                "client_id": "test",
                "redirect_uris": []
            })
            mock_post.return_value.__aenter__.return_value = mock_response
            
            # Should not raise error
            result = await dcr_service.register_client(
                gateway_id="test-gw",
                gateway_name="Test",
                issuer="https://as.example.com",  # In allowlist
                redirect_uri="http://localhost:4444/callback",
                scopes=["mcp:read"],
                db=test_db
            )


class TestDcrError:
    """Test DCR error exception."""

    def test_dcr_error_can_be_raised(self):
        """Test that DcrError can be raised and caught."""
        with pytest.raises(DcrError):
            raise DcrError("Test error")

    def test_dcr_error_preserves_message(self):
        """Test that DcrError preserves error message."""
        try:
            raise DcrError("Custom error message")
        except DcrError as e:
            assert str(e) == "Custom error message"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

