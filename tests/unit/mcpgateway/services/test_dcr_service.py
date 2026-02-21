# -*- coding: utf-8 -*-
"""Test DCR Service (RFC 7591 Dynamic Client Registration).

This test suite validates the DCR service implementation following TDD Red Phase.
Tests will FAIL until implementation is complete.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
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
            "grant_types_supported": ["authorization_code", "refresh_token"],
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value=mock_metadata)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(dcr_service, "_get_client", return_value=mock_client):
            result = await dcr_service.discover_as_metadata("https://as.example.com")

            assert result["issuer"] == "https://as.example.com"
            assert "registration_endpoint" in result
            assert result["registration_endpoint"] == "https://as.example.com/register"

    @pytest.mark.asyncio
    async def test_discover_as_metadata_tries_rfc8414_first(self):
        """Test that RFC 8414 path is tried first."""
        # Clear cache to ensure test isolation
        from mcpgateway.services.dcr_service import _metadata_cache

        _metadata_cache.clear()

        dcr_service = DcrService()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"issuer": "https://as.example.com"})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(dcr_service, "_get_client", return_value=mock_client):
            await dcr_service.discover_as_metadata("https://as.example.com")

            # First call should be RFC 8414 path
            first_call_url = mock_client.get.call_args_list[0][0][0]
            assert "/.well-known/oauth-authorization-server" in first_call_url

    @pytest.mark.asyncio
    async def test_discover_as_metadata_normalizes_trailing_slash(self):
        """Test that trailing slashes are normalized for discovery and validation.

        This tests the fix for MCP Python SDK issue #1919 where Pydantic's AnyHttpUrl
        adds trailing slashes to bare hostnames, causing issuer mismatch errors.
        """
        # Clear cache
        from mcpgateway.services.dcr_service import _metadata_cache

        _metadata_cache.clear()

        dcr_service = DcrService()

        # Server returns issuer WITHOUT trailing slash (common behavior)
        mock_metadata = {"issuer": "https://as.example.com"}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value=mock_metadata)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(dcr_service, "_get_client", return_value=mock_client):
            # Call with trailing slash (simulating MCP SDK behavior)
            result = await dcr_service.discover_as_metadata("https://as.example.com/")

            # Should succeed without raising issuer mismatch error
            assert result["issuer"] == "https://as.example.com"

            # Verify the discovery URL was constructed correctly (no double slashes)
            call_url = mock_client.get.call_args_list[0][0][0]
            assert call_url == "https://as.example.com/.well-known/oauth-authorization-server"
            assert "//.well-known" not in call_url

    @pytest.mark.asyncio
    async def test_discover_as_metadata_cache_uses_normalized_issuer(self):
        """Test that cache lookup uses normalized issuer to avoid cache misses."""
        from mcpgateway.services.dcr_service import _metadata_cache

        _metadata_cache.clear()

        dcr_service = DcrService()

        mock_metadata = {"issuer": "https://as.example.com"}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value=mock_metadata)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(dcr_service, "_get_client", return_value=mock_client):
            # First call with trailing slash
            await dcr_service.discover_as_metadata("https://as.example.com/")

            # Second call without trailing slash should hit cache
            await dcr_service.discover_as_metadata("https://as.example.com")

            # Should only have made one HTTP request (second call used cache)
            assert mock_client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_discover_as_metadata_falls_back_to_oidc(self):
        """Test fallback to OIDC discovery if RFC 8414 fails."""
        # Clear cache
        from mcpgateway.services.dcr_service import _metadata_cache

        _metadata_cache.clear()

        dcr_service = DcrService()

        # First call (RFC 8414) fails
        mock_response_404 = MagicMock()
        mock_response_404.status_code = 404

        # Second call (OIDC) succeeds
        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.json = MagicMock(return_value={"issuer": "https://as.example.com"})

        # Mock get to return different responses
        call_count = [0]

        async def get_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_response_404
            else:
                return mock_response_200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=get_side_effect)

        with patch.object(dcr_service, "_get_client", return_value=mock_client):
            result = await dcr_service.discover_as_metadata("https://as.example.com")

            # Should have tried both paths
            assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_discover_as_metadata_not_found(self):
        """Test when metadata endpoints return 404."""
        # Clear cache
        from mcpgateway.services.dcr_service import _metadata_cache

        _metadata_cache.clear()

        dcr_service = DcrService()

        # Both RFC 8414 and OIDC return 404
        mock_response_404 = MagicMock()
        mock_response_404.status_code = 404

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response_404)

        with patch.object(dcr_service, "_get_client", return_value=mock_client):
            with pytest.raises(DcrError, match="not found|Failed to discover"):
                await dcr_service.discover_as_metadata("https://as.example.com")

    @pytest.mark.asyncio
    async def test_discover_as_metadata_caches_result(self):
        """Test that metadata is cached to avoid repeated requests."""
        # Clear cache first
        from mcpgateway.services.dcr_service import _metadata_cache

        _metadata_cache.clear()

        dcr_service = DcrService()

        mock_metadata = {"issuer": "https://as.example.com"}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value=mock_metadata)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(dcr_service, "_get_client", return_value=mock_client):
            # First call
            result1 = await dcr_service.discover_as_metadata("https://as.example.com")

            # Second call should use cache
            result2 = await dcr_service.discover_as_metadata("https://as.example.com")

            # Should only have called API once
            assert mock_client.get.call_count == 1
            assert result1 == result2

    @pytest.mark.asyncio
    async def test_discover_as_metadata_validates_issuer(self):
        """Test that discovered metadata validates issuer matches."""
        # Clear cache
        from mcpgateway.services.dcr_service import _metadata_cache

        _metadata_cache.clear()

        dcr_service = DcrService()

        mock_metadata = {
            "issuer": "https://different-issuer.com",  # Doesn't match
            "authorization_endpoint": "https://as.example.com/authorize",
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value=mock_metadata)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(dcr_service, "_get_client", return_value=mock_client):
            with pytest.raises(DcrError, match="issuer mismatch"):
                await dcr_service.discover_as_metadata("https://as.example.com")

    @pytest.mark.asyncio
    async def test_discover_as_metadata_rfc8414_path_construction(self):
        """Test correct RFC 8414 URL construction for issuers with path components.

        Per RFC 8414 Section 3.1, the well-known suffix MUST be inserted between
        the host and the path.
        """
        # Clear cache
        from mcpgateway.services.dcr_service import _metadata_cache
        _metadata_cache.clear()

        dcr_service = DcrService()

        # Issuer with a path
        issuer = "https://as.example.com/tenant1"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"issuer": issuer})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(dcr_service, "_get_client", return_value=mock_client):
            await dcr_service.discover_as_metadata(issuer)

            # Verify the discovery URL was constructed correctly (suffix between host and path)
            call_url = mock_client.get.call_args_list[0][0][0]
            expected_url = "https://as.example.com/.well-known/oauth-authorization-server/tenant1"
            assert call_url == expected_url


class TestRegisterClient:
    """Test client registration (RFC 7591)."""

    @pytest.mark.asyncio
    async def test_register_client_success(self, test_db):
        """Test successful client registration."""
        dcr_service = DcrService()

        mock_metadata = {"registration_endpoint": "https://as.example.com/register"}

        mock_registration_response = {
            "client_id": "dcr-generated-client-123",
            "client_secret": "dcr-generated-secret-xyz",
            "client_id_issued_at": 1234567890,
            "redirect_uris": ["http://localhost:4444/oauth/callback"],
            "grant_types": ["authorization_code"],
            "token_endpoint_auth_method": "client_secret_basic",
            "registration_client_uri": "https://as.example.com/register/dcr-generated-client-123",
            "registration_access_token": "registration-token-abc",
        }

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json = MagicMock(return_value=mock_registration_response)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(dcr_service, "discover_as_metadata") as mock_discover, patch.object(dcr_service, "_get_client", return_value=mock_client):
            mock_discover.return_value = mock_metadata

            result = await dcr_service.register_client(
                gateway_id="test-gw-123",
                gateway_name="Test Gateway",
                issuer="https://as.example.com",
                redirect_uri="http://localhost:4444/oauth/callback",
                scopes=["mcp:read", "mcp:tools"],
                db=test_db,
            )

            assert result.client_id == "dcr-generated-client-123"
            assert result.issuer == "https://as.example.com"
            assert result.gateway_id == "test-gw-123"
            # Secret should be encrypted (not plaintext)
            assert result.client_secret_encrypted != "dcr-generated-secret-xyz"
            # Should be base64-encoded (Fernet encryption)
            assert len(result.client_secret_encrypted) > 50

    @pytest.mark.asyncio
    async def test_register_client_builds_correct_request(self, test_db):
        """Test that registration request has correct RFC 7591 fields."""
        dcr_service = DcrService()

        # AS does not advertise refresh_token support
        mock_metadata = {"registration_endpoint": "https://as.example.com/register"}

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json = MagicMock(return_value={"client_id": "test", "redirect_uris": []})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(dcr_service, "discover_as_metadata") as mock_discover, patch.object(dcr_service, "_get_client", return_value=mock_client):
            mock_discover.return_value = mock_metadata

            await dcr_service.register_client(
                gateway_id="test-gw", gateway_name="Test Gateway", issuer="https://as.example.com", redirect_uri="http://localhost:4444/callback", scopes=["mcp:read"], db=test_db
            )

            # Verify request payload
            call_kwargs = mock_client.post.call_args[1]
            request_json = call_kwargs["json"]

            assert request_json["client_name"] == "MCP Gateway (Test Gateway)"
            assert request_json["redirect_uris"] == ["http://localhost:4444/callback"]
            # Only authorization_code when AS doesn't advertise refresh_token support
            assert request_json["grant_types"] == ["authorization_code"]
            assert request_json["response_types"] == ["code"]
            assert request_json["scope"] == "mcp:read"

    @pytest.mark.asyncio
    async def test_register_client_includes_refresh_token_when_supported(self, test_db):
        """Test that refresh_token is included when AS advertises support."""
        dcr_service = DcrService()

        # AS advertises refresh_token support
        mock_metadata = {
            "registration_endpoint": "https://as.example.com/register",
            "grant_types_supported": ["authorization_code", "refresh_token"],
        }

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json = MagicMock(return_value={"client_id": "test", "redirect_uris": []})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(dcr_service, "discover_as_metadata") as mock_discover, patch.object(dcr_service, "_get_client", return_value=mock_client):
            mock_discover.return_value = mock_metadata

            await dcr_service.register_client(
                gateway_id="test-gw-refresh", gateway_name="Test Gateway", issuer="https://as.example.com", redirect_uri="http://localhost:4444/callback", scopes=["mcp:read"], db=test_db
            )

            # Verify request payload includes refresh_token
            call_kwargs = mock_client.post.call_args[1]
            request_json = call_kwargs["json"]

            assert request_json["grant_types"] == ["authorization_code", "refresh_token"]

    @pytest.mark.asyncio
    async def test_register_client_stores_requested_grant_types_as_fallback(self, test_db):
        """Test that requested grant_types are stored when AS response omits them."""
        dcr_service = DcrService()

        mock_metadata = {
            "registration_endpoint": "https://as.example.com/register",
            "grant_types_supported": ["authorization_code", "refresh_token"],
        }

        # AS response omits grant_types
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json = MagicMock(return_value={"client_id": "test-fallback", "redirect_uris": []})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(dcr_service, "discover_as_metadata") as mock_discover, patch.object(dcr_service, "_get_client", return_value=mock_client):
            mock_discover.return_value = mock_metadata

            result = await dcr_service.register_client(
                gateway_id="test-gw-fallback", gateway_name="Test Gateway", issuer="https://as.example.com", redirect_uri="http://localhost:4444/callback", scopes=["mcp:read"], db=test_db
            )

            # Stored grant_types should be the requested ones, not hardcoded fallback
            import orjson

            stored_grant_types = orjson.loads(result.grant_types)
            assert stored_grant_types == ["authorization_code", "refresh_token"]

    @pytest.mark.asyncio
    async def test_register_client_handles_null_grant_types_supported(self, test_db):
        """Test that explicit null grant_types_supported doesn't cause TypeError.

        Some AS servers return {"grant_types_supported": null} instead of omitting the field.
        This should be handled gracefully without raising TypeError.
        """
        dcr_service = DcrService()

        # AS returns explicit null for grant_types_supported
        mock_metadata = {
            "registration_endpoint": "https://as.example.com/register",
            "grant_types_supported": None,  # Explicit null, not missing
        }

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json = MagicMock(return_value={"client_id": "test-null", "redirect_uris": []})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(dcr_service, "discover_as_metadata") as mock_discover, patch.object(dcr_service, "_get_client", return_value=mock_client):
            mock_discover.return_value = mock_metadata

            # Should not raise TypeError
            result = await dcr_service.register_client(
                gateway_id="test-gw-null", gateway_name="Test", issuer="https://as.example.com", redirect_uri="http://localhost:4444/callback", scopes=["mcp:read"], db=test_db
            )

            # Should only request authorization_code (strict mode)
            call_kwargs = mock_client.post.call_args[1]
            request_json = call_kwargs["json"]
            assert request_json["grant_types"] == ["authorization_code"]

    @pytest.mark.asyncio
    async def test_register_client_permissive_refresh_token_mode(self, test_db):
        """Test that permissive mode requests refresh_token when AS omits grant_types_supported."""
        dcr_service = DcrService()

        # AS omits grant_types_supported entirely
        mock_metadata = {
            "registration_endpoint": "https://as.example.com/register",
            # No grant_types_supported field
        }

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json = MagicMock(return_value={"client_id": "test-permissive", "redirect_uris": []})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        # Enable permissive mode
        with (
            patch.object(dcr_service.settings, "dcr_request_refresh_token_when_unsupported", True),
            patch.object(dcr_service, "discover_as_metadata") as mock_discover,
            patch.object(dcr_service, "_get_client", return_value=mock_client),
        ):
            mock_discover.return_value = mock_metadata

            result = await dcr_service.register_client(
                gateway_id="test-gw-permissive", gateway_name="Test", issuer="https://as.example.com", redirect_uri="http://localhost:4444/callback", scopes=["mcp:read"], db=test_db
            )

            # Should request both authorization_code and refresh_token in permissive mode
            call_kwargs = mock_client.post.call_args[1]
            request_json = call_kwargs["json"]
            assert request_json["grant_types"] == ["authorization_code", "refresh_token"]

    @pytest.mark.asyncio
    async def test_register_client_no_registration_endpoint(self, test_db):
        """Test registration failure when AS doesn't support DCR."""
        dcr_service = DcrService()

        mock_metadata = {
            "issuer": "https://as.example.com",
            # No registration_endpoint
        }

        with patch.object(dcr_service, "discover_as_metadata") as mock_discover:
            mock_discover.return_value = mock_metadata

            with pytest.raises(DcrError, match="does not support Dynamic Client Registration"):
                await dcr_service.register_client(
                    gateway_id="test-gw", gateway_name="Test", issuer="https://as.example.com", redirect_uri="http://localhost:4444/callback", scopes=["mcp:read"], db=test_db
                )

    @pytest.mark.asyncio
    async def test_register_client_handles_registration_error(self, test_db):
        """Test handling of registration errors (invalid_redirect_uri, etc.)."""
        dcr_service = DcrService()

        mock_metadata = {"registration_endpoint": "https://as.example.com/register"}

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json = MagicMock(return_value={"error": "invalid_redirect_uri", "error_description": "Redirect URI not allowed"})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(dcr_service, "discover_as_metadata") as mock_discover, patch.object(dcr_service, "_get_client", return_value=mock_client):
            mock_discover.return_value = mock_metadata

            with pytest.raises(DcrError, match="invalid_redirect_uri"):
                await dcr_service.register_client(gateway_id="test-gw", gateway_name="Test", issuer="https://as.example.com", redirect_uri="http://invalid", scopes=["mcp:read"], db=test_db)

    @pytest.mark.asyncio
    async def test_register_client_stores_encrypted_secret(self, test_db):
        """Test that client_secret is encrypted before storage."""
        dcr_service = DcrService()

        mock_metadata = {"registration_endpoint": "https://as.example.com/register"}
        mock_registration = {"client_id": "test-client-encrypt", "client_secret": "plaintext-secret", "redirect_uris": ["http://localhost:4444/callback"]}

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json = MagicMock(return_value=mock_registration)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(dcr_service, "discover_as_metadata") as mock_discover, patch.object(dcr_service, "_get_client", return_value=mock_client):
            mock_discover.return_value = mock_metadata

            result = await dcr_service.register_client(
                gateway_id="test-gw-encrypt",  # Unique gateway ID
                gateway_name="Test",
                issuer="https://as.example.com",
                redirect_uri="http://localhost:4444/callback",
                scopes=["mcp:read"],
                db=test_db,
            )

            # Secret should NOT be stored as plaintext
            assert result.client_secret_encrypted != "plaintext-secret"
            # Should be encrypted (base64-encoded)
            assert len(result.client_secret_encrypted) > 50


class TestGetOrRegisterClient:
    """Test get-or-create pattern for DCR."""

    @pytest.mark.asyncio
    async def test_get_or_register_client_returns_existing(self, test_db):
        """Test that existing client is returned if found."""
        dcr_service = DcrService()

        # Mock existing client in database
        from mcpgateway.db import RegisteredOAuthClient, Gateway

        # Add gateway first
        gateway = Gateway(id="test-gw-existing", name="Test", slug="test", url="http://test.example.com", description="Test", capabilities={})
        test_db.add(gateway)
        test_db.commit()

        existing_client = RegisteredOAuthClient(
            id="existing-id",
            gateway_id="test-gw-existing",
            issuer="https://as-existing.example.com",
            client_id="existing-client",
            client_secret_encrypted="encrypted",
            redirect_uris='["http://localhost:4444/callback"]',
            grant_types='["authorization_code"]',
            is_active=True,
        )
        test_db.add(existing_client)
        test_db.commit()

        result = await dcr_service.get_or_register_client(
            gateway_id="test-gw-existing", gateway_name="Test", issuer="https://as-existing.example.com", redirect_uri="http://localhost:4444/callback", scopes=["mcp:read"], db=test_db
        )

        assert result.id == "existing-id"
        assert result.client_id == "existing-client"

    @pytest.mark.asyncio
    async def test_get_or_register_client_registers_if_not_found(self, test_db):
        """Test that new client is registered if not found."""
        dcr_service = DcrService()

        with patch.object(dcr_service, "register_client") as mock_register:
            from mcpgateway.db import RegisteredOAuthClient

            mock_register.return_value = RegisteredOAuthClient(
                id="new-id", gateway_id="test-gw-new-reg", issuer="https://as-new.example.com", client_id="new-client", client_secret_encrypted="encrypted", redirect_uris="[]", grant_types="[]"
            )

            result = await dcr_service.get_or_register_client(
                gateway_id="test-gw-new-reg", gateway_name="Test", issuer="https://as-new.example.com", redirect_uri="http://localhost:4444/callback", scopes=["mcp:read"], db=test_db
            )

            mock_register.assert_called_once()
            assert result.client_id == "new-client"

    @pytest.mark.asyncio
    async def test_get_or_register_client_respects_auto_register_flag(self, test_db):
        """Test that auto-register flag is respected."""
        dcr_service = DcrService()

        # Patch the settings on the dcr_service instance
        with patch.object(dcr_service.settings, "dcr_auto_register_on_missing_credentials", False):
            with pytest.raises(DcrError, match="Auto-register is disabled|auto-register is disabled"):
                await dcr_service.get_or_register_client(
                    gateway_id="test-gw-autoreg", gateway_name="Test", issuer="https://as-autoreg.example.com", redirect_uri="http://localhost:4444/callback", scopes=["mcp:read"], db=test_db
                )


class TestUpdateClientRegistration:
    """Test updating client registration (RFC 7591 section 4.2)."""

    @pytest.mark.asyncio
    async def test_update_client_registration_success(self, test_db):
        """Test successful client registration update."""
        from mcpgateway.services.encryption_service import get_encryption_service
        from mcpgateway.config import get_settings

        dcr_service = DcrService()

        from mcpgateway.db import RegisteredOAuthClient, Gateway

        # Add gateway first
        gateway = Gateway(id="test-gw-update", name="Test", slug="test-update", url="http://test-update.example.com", description="Test", capabilities={})
        test_db.add(gateway)
        test_db.commit()

        # Encrypt the registration access token properly
        encryption = get_encryption_service(get_settings().auth_encryption_secret)
        encrypted_token = encryption.encrypt_secret("registration-access-token")

        client_record = RegisteredOAuthClient(
            id="client-id-update",
            gateway_id="test-gw-update",
            issuer="https://as-update.example.com",
            client_id="test-client-update",
            client_secret_encrypted="encrypted",
            registration_client_uri="https://as-update.example.com/register/test-client",
            registration_access_token_encrypted=encrypted_token,
            redirect_uris='["http://localhost:4444/callback"]',
            grant_types='["authorization_code"]',
        )
        test_db.add(client_record)
        test_db.commit()

        mock_response = {"client_id": "test-client-update", "client_secret": "updated-secret", "redirect_uris": ["http://localhost:4444/callback", "http://localhost:4444/callback2"]}

        mock_response_obj = MagicMock()
        mock_response_obj.status_code = 200
        mock_response_obj.json = MagicMock(return_value=mock_response)

        mock_client = AsyncMock()
        mock_client.put = AsyncMock(return_value=mock_response_obj)

        with patch.object(dcr_service, "_get_client", return_value=mock_client):
            result = await dcr_service.update_client_registration(client_record, test_db)

            assert result.client_id == "test-client-update"

    @pytest.mark.asyncio
    async def test_update_client_registration_uses_access_token(self, test_db):
        """Test that update uses registration_access_token."""
        from mcpgateway.services.encryption_service import get_encryption_service
        from mcpgateway.config import get_settings

        dcr_service = DcrService()

        from mcpgateway.db import RegisteredOAuthClient, Gateway

        # Add gateway first
        gateway = Gateway(id="test-gw-update-auth", name="Test", slug="test-update-auth", url="http://test-update-auth.example.com", description="Test", capabilities={})
        test_db.add(gateway)
        test_db.commit()

        # Encrypt the registration access token properly
        encryption = get_encryption_service(get_settings().auth_encryption_secret)
        encrypted_token = encryption.encrypt_secret("registration-access-token")

        client_record = RegisteredOAuthClient(
            id="client-id-auth",
            gateway_id="test-gw-update-auth",
            issuer="https://as-update-auth.example.com",
            client_id="test-client-auth",
            client_secret_encrypted="encrypted",
            registration_client_uri="https://as-update-auth.example.com/register/test-client",
            registration_access_token_encrypted=encrypted_token,
            redirect_uris="[]",
            grant_types="[]",
        )
        test_db.add(client_record)
        test_db.commit()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value={"client_id": "test-client-auth"})

        mock_client = AsyncMock()
        mock_client.put = AsyncMock(return_value=mock_response)

        with patch.object(dcr_service, "_get_client", return_value=mock_client):
            await dcr_service.update_client_registration(client_record, test_db)

            # Verify Bearer token was used
            call_kwargs = mock_client.put.call_args[1]
            assert "Authorization" in call_kwargs["headers"]
            assert call_kwargs["headers"]["Authorization"].startswith("Bearer ")
    @pytest.mark.asyncio
    async def test_update_client_registration_decryption_failure(self, test_db):
        """Test that update raises DcrError when token decryption fails."""
        from mcpgateway.services.encryption_service import EncryptionService
        from mcpgateway.config import get_settings

        dcr_service = DcrService()

        from mcpgateway.db import RegisteredOAuthClient, Gateway

        # Add gateway first
        gateway = Gateway(id="test-gw-update-decrypt-fail", name="Test", slug="test-update-decrypt-fail", url="http://test-update-decrypt-fail.example.com", description="Test", capabilities={})
        test_db.add(gateway)
        test_db.commit()

        client_record = RegisteredOAuthClient(
            id="client-id-decrypt-fail",
            gateway_id="test-gw-update-decrypt-fail",
            issuer="https://as-update-decrypt-fail.example.com",
            client_id="test-client-decrypt-fail",
            client_secret_encrypted="encrypted",
            registration_client_uri="https://as-update-decrypt-fail.example.com/register/test-client",
            registration_access_token_encrypted="v2:{invalid_json}",  # Will fail decryption
            redirect_uris="[]",
            grant_types="[]",
        )
        test_db.add(client_record)
        test_db.commit()

        # Mock decrypt to return None (failure)
        with patch.object(EncryptionService, "decrypt_secret_async", return_value=None):
            with pytest.raises(DcrError, match="Failed to decrypt registration access token for update operation"):
                await dcr_service.update_client_registration(client_record, test_db)



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
            redirect_uris="[]",
            grant_types="[]",
        )

        mock_response = MagicMock()
        mock_response.status_code = 204

        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(return_value=mock_response)

        with patch.object(dcr_service, "_get_client", return_value=mock_client):
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
            redirect_uris="[]",
            grant_types="[]",
        )

        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(return_value=mock_response)

        with patch.object(dcr_service, "_get_client", return_value=mock_client):
            # Should still return True (client is gone)
            result = await dcr_service.delete_client_registration(client_record, test_db)

            assert result is True

    @pytest.mark.asyncio
    async def test_delete_client_registration_missing_uri(self, test_db):
        """Test that deletion returns False when registration_client_uri is missing."""
        dcr_service = DcrService()

        from mcpgateway.db import RegisteredOAuthClient

        client_record = RegisteredOAuthClient(
            id="client-id",
            gateway_id="test-gw",
            issuer="https://as.example.com",
            client_id="test-client",
            client_secret_encrypted="encrypted",
            registration_client_uri=None,  # Missing URI
            registration_access_token_encrypted="encrypted-token",
            redirect_uris="[]",
            grant_types="[]",
        )

        result = await dcr_service.delete_client_registration(client_record, test_db)
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_client_registration_missing_token(self, test_db):
        """Test that deletion returns False when registration_access_token_encrypted is missing."""
        dcr_service = DcrService()

        from mcpgateway.db import RegisteredOAuthClient

        client_record = RegisteredOAuthClient(
            id="client-id",
            gateway_id="test-gw",
            issuer="https://as.example.com",
            client_id="test-client",
            client_secret_encrypted="encrypted",
            registration_client_uri="https://as.example.com/register/test-client",
            registration_access_token_encrypted=None,  # Missing token
            redirect_uris="[]",
            grant_types="[]",
        )

        result = await dcr_service.delete_client_registration(client_record, test_db)
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_client_registration_decryption_failure(self, test_db):
        """Test that deletion returns False when token decryption fails."""
        dcr_service = DcrService()

        from mcpgateway.db import RegisteredOAuthClient
        from mcpgateway.services.encryption_service import EncryptionService

        client_record = RegisteredOAuthClient(
            id="client-id",
            gateway_id="test-gw",
            issuer="https://as.example.com",
            client_id="test-client",
            client_secret_encrypted="encrypted",
            registration_client_uri="https://as.example.com/register/test-client",
            registration_access_token_encrypted="v2:{invalid_json}",  # Will fail decryption
            redirect_uris="[]",
            grant_types="[]",
        )

        # Mock decrypt to return None (failure)
        with patch.object(EncryptionService, "decrypt_secret_async", return_value=None):
            result = await dcr_service.delete_client_registration(client_record, test_db)
            assert result is False

    @pytest.mark.asyncio
    async def test_delete_client_registration_unexpected_status(self, test_db):
        """Test that deletion returns False for unexpected HTTP status."""
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
            redirect_uris="[]",
            grant_types="[]",
        )

        mock_response = MagicMock()
        mock_response.status_code = 500  # Unexpected status

        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(return_value=mock_response)

        with patch.object(dcr_service, "_get_client", return_value=mock_client):
            result = await dcr_service.delete_client_registration(client_record, test_db)
            assert result is False

    @pytest.mark.asyncio
    async def test_delete_client_registration_network_error(self, test_db):
        """Test that deletion returns False on network error."""
        dcr_service = DcrService()

        from mcpgateway.db import RegisteredOAuthClient
        import httpx

        client_record = RegisteredOAuthClient(
            id="client-id",
            gateway_id="test-gw",
            issuer="https://as.example.com",
            client_id="test-client",
            client_secret_encrypted="encrypted",
            registration_client_uri="https://as.example.com/register/test-client",
            registration_access_token_encrypted="encrypted-token",
            redirect_uris="[]",
            grant_types="[]",
        )

        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(side_effect=httpx.HTTPError("Network error"))

        with patch.object(dcr_service, "_get_client", return_value=mock_client):
            result = await dcr_service.delete_client_registration(client_record, test_db)
            assert result is False


class TestIssuerValidation:
    """Test issuer allowlist validation."""

    @pytest.mark.asyncio
    async def test_issuer_validation_allows_when_list_empty(self, test_db):
        """Test that empty allowlist allows all issuers."""
        dcr_service = DcrService()

        from mcpgateway.config import get_settings

        with patch.object(get_settings(), "dcr_allowed_issuers", []):
            # Should not raise error
            pass  # Validation happens in register_client

    @pytest.mark.asyncio
    async def test_issuer_validation_blocks_unauthorized(self, test_db):
        """Test that unauthorized issuer is blocked."""
        dcr_service = DcrService()

        from mcpgateway.config import get_settings

        with patch.object(get_settings(), "dcr_allowed_issuers", ["https://trusted.com"]):
            with pytest.raises(DcrError, match="not in allowed issuers"):
                await dcr_service.register_client(
                    gateway_id="test-gw",
                    gateway_name="Test",
                    issuer="https://untrusted.com",  # Not in allowlist
                    redirect_uri="http://localhost:4444/callback",
                    scopes=["mcp:read"],
                    db=test_db,
                )

    @pytest.mark.asyncio
    async def test_issuer_validation_allows_authorized(self, test_db):
        """Test that authorized issuer is allowed."""
        dcr_service = DcrService()

        from mcpgateway.db import Gateway

        # Add gateway first
        gateway = Gateway(id="test-gw-issuer-auth", name="Test", slug="test-issuer-auth", url="http://test-issuer-auth.example.com", description="Test", capabilities={})
        test_db.add(gateway)
        test_db.commit()

        # Patch settings on the instance
        with (
            patch.object(dcr_service.settings, "dcr_allowed_issuers", ["https://as-issuer-auth.example.com"]),
            patch.object(dcr_service, "discover_as_metadata") as mock_discover,
        ):
            mock_discover.return_value = {"registration_endpoint": "https://as-issuer-auth.example.com/register"}

            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json = MagicMock(return_value={"client_id": "test-issuer-auth", "redirect_uris": []})

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)

            with patch.object(dcr_service, "_get_client", return_value=mock_client):
                # Should not raise error
                result = await dcr_service.register_client(
                    gateway_id="test-gw-issuer-auth",
                    gateway_name="Test",
                    issuer="https://as-issuer-auth.example.com",  # In allowlist
                    redirect_uri="http://localhost:4444/callback",
                    scopes=["mcp:read"],
                    db=test_db,
                )

    @pytest.mark.asyncio
    async def test_issuer_validation_normalizes_trailing_slash(self, test_db):
        """Test that allowlist comparison normalizes trailing slashes.

        This ensures that issuer with trailing slash (e.g., from MCP SDK's Pydantic AnyHttpUrl)
        matches an allowlist entry without trailing slash, and vice versa.
        """
        dcr_service = DcrService()

        from mcpgateway.db import Gateway

        # Add gateway first
        gateway = Gateway(id="test-gw-issuer-slash", name="Test", slug="test-issuer-slash", url="http://test.example.com", description="Test", capabilities={})
        test_db.add(gateway)
        test_db.commit()

        # Allowlist has NO trailing slash, but issuer has trailing slash (MCP SDK behavior)
        with (
            patch.object(dcr_service.settings, "dcr_allowed_issuers", ["https://as-slash.example.com"]),
            patch.object(dcr_service, "discover_as_metadata") as mock_discover,
        ):
            mock_discover.return_value = {"registration_endpoint": "https://as-slash.example.com/register"}

            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json = MagicMock(return_value={"client_id": "test-slash", "redirect_uris": []})

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)

            with patch.object(dcr_service, "_get_client", return_value=mock_client):
                # Should not raise error - trailing slash should be normalized
                result = await dcr_service.register_client(
                    gateway_id="test-gw-issuer-slash",
                    gateway_name="Test",
                    issuer="https://as-slash.example.com/",  # Has trailing slash
                    redirect_uri="http://localhost:4444/callback",
                    scopes=["mcp:read"],
                    db=test_db,
                )

                # Verify the stored issuer is normalized (no trailing slash)
                assert result.issuer == "https://as-slash.example.com"


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
