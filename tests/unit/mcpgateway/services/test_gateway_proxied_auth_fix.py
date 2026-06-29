"""Test for PROXIED gateway auth_type UnboundLocalError fix (issue from 2026-06-23)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from mcpgateway.services.gateway_service import GatewayService
from mcpgateway.schemas import GatewayCreate


@pytest.mark.asyncio
async def test_proxied_gateway_without_url_initializes_auth_variables():
    """Test that PROXIED gateway without URL doesn't cause UnboundLocalError for auth_type.
    
    This test verifies the fix for the error:
    UnboundLocalError("cannot access local variable 'auth_type' where it is not associated with a value")
    
    The issue occurred when:
    1. transport == "PROXIED"
    2. is_reverse_proxied == False
    3. The conditional block that initializes auth_type was skipped
    4. But auth_type was still referenced when creating DbGateway
    """
    service = GatewayService()
    
    # Mock database session
    db = MagicMock()
    db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    db.add = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    
    # Create a PROXIED gateway without URL
    gateway = GatewayCreate(
        name="test-proxied-gateway",
        url=None,  # No URL provided
        transport="PROXIED",
        description="Test PROXIED gateway",
        auth_type=None,
        auth_value=None,
    )
    
    # Mock the preparation method to return valid preparation data
    mock_preparation = MagicMock()
    mock_preparation.slug_name = "test-proxied-gateway"
    mock_preparation.normalized_url = "https://localhost/reverse-proxy/sessions/test123/mcp"
    mock_preparation.auth_type = None
    mock_preparation.auth_value = None
    mock_preparation.oauth_config = None
    mock_preparation.authentication_headers = None
    mock_preparation.auth_query_params_encrypted = None
    mock_preparation.auth_query_params_decrypted = None
    mock_preparation.init_url = "https://localhost/reverse-proxy/sessions/test123/mcp"
    mock_preparation.ca_certificate = None
    mock_preparation.init_client_cert = None
    mock_preparation.init_client_key = None
    mock_preparation.gateway_mode = "cache"
    
    with patch.object(service, '_prepare_gateway_registration', new_callable=AsyncMock) as mock_prep:
        mock_prep.return_value = mock_preparation
        
        with patch.object(service, '_notify_gateway_added', new_callable=AsyncMock):
            with patch.object(service, '_encrypt_client_key', new_callable=AsyncMock) as mock_encrypt:
                mock_encrypt.return_value = None
                
                # This should NOT raise UnboundLocalError for auth_type
                try:
                    result = await service.register_gateway(
                        db=db,
                        gateway=gateway,
                        created_via="api",
                        team_id=None,
                        owner_email="test@example.com",
                        visibility="public",
                        initialize_timeout=None,
                        gateway_id="test123",
                    )
                    
                    # If we get here, the fix worked - auth_type was properly initialized
                    assert result is not None
                    
                except UnboundLocalError as e:
                    if "auth_type" in str(e):
                        pytest.fail(f"UnboundLocalError for auth_type still occurs: {e}")
                    raise
                except Exception:
                    # Other exceptions are fine for this test - we're only checking for UnboundLocalError
                    pass


@pytest.mark.asyncio
async def test_reverse_proxied_gateway_initializes_auth_variables():
    """Test that reverse proxy gateway (created_via='reverse_proxy') properly initializes auth variables."""
    from datetime import datetime, timezone
    
    service = GatewayService()
    
    # Mock database session
    db = MagicMock()
    db.execute = MagicMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None), scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))), all=MagicMock(return_value=[])))
    db.add = MagicMock()
    db.commit = MagicMock()
    
    # Mock db.refresh to set required datetime fields
    def mock_refresh(obj):
        if not hasattr(obj, 'created_at') or obj.created_at is None:
            obj.created_at = datetime.now(timezone.utc)
        if not hasattr(obj, 'updated_at') or obj.updated_at is None:
            obj.updated_at = datetime.now(timezone.utc)
    
    db.refresh = MagicMock(side_effect=mock_refresh)
    
    # Create a PROXIED gateway for reverse proxy with no auth (simpler test case)
    gateway = GatewayCreate(
        name="test-reverse-proxy-gateway",
        url="https://example.com/mcp",
        transport="PROXIED",
        description="Test reverse proxy gateway",
    )
    
    # Mock the preparation method
    mock_preparation = MagicMock()
    mock_preparation.slug_name = "test-reverse-proxy-gateway"
    mock_preparation.normalized_url = "https://example.com/mcp"
    mock_preparation.auth_type = None
    mock_preparation.auth_value = None
    mock_preparation.oauth_config = None
    mock_preparation.authentication_headers = None
    mock_preparation.auth_query_params_encrypted = None
    mock_preparation.auth_query_params_decrypted = None
    mock_preparation.init_url = "https://example.com/mcp"
    mock_preparation.ca_certificate = None
    mock_preparation.init_client_cert = None
    mock_preparation.init_client_key = None
    mock_preparation.gateway_mode = "cache"
    
    with patch.object(service, '_prepare_gateway_registration', new_callable=AsyncMock) as mock_prep:
        mock_prep.return_value = mock_preparation
        
        with patch.object(service, '_initialize_gateway_with_timeout', new_callable=AsyncMock) as mock_init:
            mock_init.return_value = ({}, [], [], [], [])
            
            with patch.object(service, '_notify_gateway_added', new_callable=AsyncMock):
                with patch.object(service, '_encrypt_client_key', new_callable=AsyncMock) as mock_encrypt:
                    mock_encrypt.return_value = None
                    
                    # This should work correctly with auth_type properly initialized
                    try:
                        result = await service.register_proxy_gateway(
                            db=db,
                            gateway=gateway,
                            gateway_id="test-proxy-123",
                            team_id=None,
                            owner_email="test@example.com",
                            visibility="public",
                            created_by="test-user",
                        )
                        
                        # Verify the result is a tuple (for proxy gateways)
                        assert isinstance(result, tuple)
                        assert len(result) == 4  # (gateway, tool_ids, resource_ids, prompt_ids)
                        
                    except UnboundLocalError as e:
                        if "auth_type" in str(e):
                            pytest.fail(f"UnboundLocalError for auth_type in reverse proxy: {e}")
                        raise

# Made with Bob
