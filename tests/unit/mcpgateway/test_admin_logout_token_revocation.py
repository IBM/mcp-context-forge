# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_admin_logout_token_revocation.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0

Unit tests for /admin/logout token revocation functionality.

Tests verify that the admin logout endpoint properly revokes tokens
in the blocklist when users log out from the admin UI.
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import uuid

# Third-Party
import jwt
import pytest
from fastapi import Request
from fastapi.responses import RedirectResponse

# First-Party
from mcpgateway.config import settings


class TestAdminLogoutTokenRevocation:
    """Test token revocation in admin logout endpoint."""

    @pytest.fixture
    def mock_request(self):
        """Create a mock FastAPI request."""
        request = MagicMock(spec=Request)
        request.method = "POST"
        request.scope = {"root_path": ""}
        request.headers = {"accept": "text/html"}
        return request

    @pytest.fixture
    def valid_jwt_token(self):
        """Create a valid JWT token for testing."""
        jti = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        payload = {
            "email": "admin@example.com",
            "jti": jti,
            "exp": int((now + timedelta(minutes=20)).timestamp()),  # Must be integer timestamp
            "last_activity": now.timestamp()
        }
        # Handle SecretStr - get the actual string value
        jwt_secret = settings.jwt_secret_key
        if hasattr(jwt_secret, 'get_secret_value'):
            jwt_secret = jwt_secret.get_secret_value()
        token = jwt.encode(payload, jwt_secret, algorithm="HS256")
        return token, jti, payload

    def test_admin_logout_revokes_token(self, mock_request, valid_jwt_token):
        """Test that admin logout revokes the token in blocklist."""
        token, jti, payload = valid_jwt_token
        
        # Set up mock request with JWT cookie
        mock_request.cookies = {"jwt_token": token}
        
        # Mock the token blocklist service at the import location
        with patch('mcpgateway.services.token_blocklist_service.get_token_blocklist_service') as mock_get_service:
            mock_blocklist_service = MagicMock()
            mock_get_service.return_value = mock_blocklist_service
            
            # Mock verify_jwt_token_cached to return our payload
            with patch('mcpgateway.admin.verify_jwt_token_cached') as mock_verify:
                mock_verify.return_value = payload
                
                # Import and call the logout function
                from mcpgateway.admin import _admin_logout
                import asyncio
                
                response = asyncio.run(_admin_logout(mock_request))
                
                # Verify token was revoked
                mock_blocklist_service.revoke_token.assert_called_once()
                call_args = mock_blocklist_service.revoke_token.call_args
                
                assert call_args.kwargs['jti'] == jti
                assert call_args.kwargs['revoked_by'] == "admin@example.com"
                assert call_args.kwargs['reason'] == "admin_logout"
                assert call_args.kwargs['token_expiry'] is not None
                assert call_args.kwargs['last_activity'] is not None

    def test_admin_logout_handles_revocation_failure_gracefully(self, mock_request, valid_jwt_token):
        """Test that admin logout continues even if token revocation fails."""
        token, jti, payload = valid_jwt_token
        
        # Set up mock request with JWT cookie
        mock_request.cookies = {"jwt_token": token}
        
        # Mock the token blocklist service to raise an exception
        with patch('mcpgateway.services.token_blocklist_service.get_token_blocklist_service') as mock_get_service:
            mock_blocklist_service = MagicMock()
            mock_blocklist_service.revoke_token.side_effect = Exception("Database error")
            mock_get_service.return_value = mock_blocklist_service
            
            # Mock verify_jwt_token_cached to return our payload
            with patch('mcpgateway.admin.verify_jwt_token_cached') as mock_verify:
                mock_verify.return_value = payload
                
                # Import and call the logout function
                from mcpgateway.admin import _admin_logout
                import asyncio
                
                # Should not raise exception - logout should continue
                response = asyncio.run(_admin_logout(mock_request))
                
                # Verify response is still a redirect (logout succeeded)
                assert isinstance(response, RedirectResponse)

    def test_admin_logout_without_jwt_cookie(self, mock_request):
        """Test that admin logout works even without JWT cookie."""
        # Set up mock request without JWT cookie
        mock_request.cookies = {}
        
        # Import and call the logout function
        from mcpgateway.admin import _admin_logout
        import asyncio
        
        # Should not raise exception
        response = asyncio.run(_admin_logout(mock_request))
        
        # Verify response is a redirect
        assert isinstance(response, RedirectResponse)

    def test_admin_logout_with_invalid_jwt(self, mock_request):
        """Test that admin logout handles invalid JWT gracefully."""
        # Set up mock request with invalid JWT
        mock_request.cookies = {"jwt_token": "invalid.jwt.token"}
        
        # Mock verify_jwt_token_cached to raise an exception
        with patch('mcpgateway.admin.verify_jwt_token_cached') as mock_verify:
            mock_verify.side_effect = Exception("Invalid token")
            
            # Import and call the logout function
            from mcpgateway.admin import _admin_logout
            import asyncio
            
            # Should not raise exception - logout should continue
            response = asyncio.run(_admin_logout(mock_request))
            
            # Verify response is still a redirect (logout succeeded)
            assert isinstance(response, RedirectResponse)

    def test_admin_logout_with_missing_jti(self, mock_request, valid_jwt_token):
        """Test that admin logout handles missing JTI gracefully."""
        token, _, payload = valid_jwt_token
        
        # Remove JTI from payload
        payload_without_jti = {k: v for k, v in payload.items() if k != 'jti'}
        
        # Set up mock request with JWT cookie
        mock_request.cookies = {"jwt_token": token}
        
        # Mock verify_jwt_token_cached to return payload without JTI
        with patch('mcpgateway.admin.verify_jwt_token_cached') as mock_verify:
            mock_verify.return_value = payload_without_jti
            
            # Mock the token blocklist service
            with patch('mcpgateway.services.token_blocklist_service.get_token_blocklist_service') as mock_get_service:
                mock_blocklist_service = MagicMock()
                mock_get_service.return_value = mock_blocklist_service
                
                # Import and call the logout function
                from mcpgateway.admin import _admin_logout
                import asyncio
                
                response = asyncio.run(_admin_logout(mock_request))
                
                # Verify token revocation was NOT called (no JTI)
                mock_blocklist_service.revoke_token.assert_not_called()
                
                # Verify response is still a redirect (logout succeeded)
                assert isinstance(response, RedirectResponse)
