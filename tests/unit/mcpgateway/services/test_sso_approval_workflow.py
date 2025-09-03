# -*- coding: utf-8 -*-
"""Test SSO user approval workflow functionality."""

# Standard
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.db import PendingUserApproval, utc_now
from mcpgateway.services.sso_service import SSOService


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = MagicMock(spec=Session)
    return session


@pytest.fixture
def sso_service(mock_db_session):
    """Create SSO service instance with mock dependencies."""
    with patch('mcpgateway.services.sso_service.EmailAuthService'):
        service = SSOService(mock_db_session)
        return service


class TestSSOApprovalWorkflow:
    """Test SSO user approval workflow functionality."""

    @pytest.mark.asyncio
    async def test_pending_approval_creation(self, sso_service):
        """Test that pending approval requests are created when required."""
        user_info = {
            "email": "newuser@example.com",
            "full_name": "New User",
            "provider": "github"
        }

        # Mock settings to require approval
        with patch('mcpgateway.services.sso_service.settings') as mock_settings:
            mock_settings.sso_require_admin_approval = True

            # Mock database queries
            sso_service.db.execute.return_value.scalar_one_or_none.return_value = None  # No existing pending approval

            # Mock get_user_by_email to return None (new user)
            with patch.object(sso_service, 'auth_service') as mock_auth_service:
                # For async methods, need to use AsyncMock
                mock_auth_service.get_user_by_email = AsyncMock(return_value=None)

                # Mock get_provider
                with patch.object(sso_service, 'get_provider') as mock_get_provider:
                    mock_provider = MagicMock()
                    mock_provider.auto_create_users = True
                    mock_provider.trusted_domains = []
                    mock_get_provider.return_value = mock_provider

                    # Should return None (no token) and create pending approval
                    result = await sso_service.authenticate_or_create_user(user_info)

                    assert result is None  # No token until approved
                    sso_service.db.add.assert_called_once()  # Pending approval was added
                    sso_service.db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_approved_user_creation(self, sso_service):
        """Test that approved users can be created successfully."""
        user_info = {
            "email": "approved@example.com",
            "full_name": "Approved User",
            "provider": "github"
        }

        # Mock settings to require approval
        with patch('mcpgateway.services.sso_service.settings') as mock_settings:
            mock_settings.sso_require_admin_approval = True

            # Mock existing approved pending approval
            mock_pending = MagicMock()
            mock_pending.status = "approved"
            mock_pending.is_expired.return_value = False
            sso_service.db.execute.return_value.scalar_one_or_none.side_effect = [mock_pending, mock_pending]

            # Mock get_user_by_email to return None (new user)
            with patch.object(sso_service, 'auth_service') as mock_auth_service:
                # For async methods, need to use AsyncMock
                mock_auth_service.get_user_by_email = AsyncMock(return_value=None)

                # Mock user creation
                mock_user = MagicMock()
                mock_user.email = "approved@example.com"
                mock_user.full_name = "Approved User"
                mock_user.is_admin = False
                mock_user.auth_provider = "github"
                mock_user.get_teams.return_value = []
                # For async methods, need to use AsyncMock
                mock_auth_service.create_user = AsyncMock(return_value=mock_user)

                # Mock get_provider
                with patch.object(sso_service, 'get_provider') as mock_get_provider:
                    mock_provider = MagicMock()
                    mock_provider.auto_create_users = True
                    mock_provider.trusted_domains = []
                    mock_get_provider.return_value = mock_provider

                    # Mock admin check
                    with patch.object(sso_service, '_should_user_be_admin') as mock_admin_check:
                        mock_admin_check.return_value = False

                        # Should create user and return token
                        with patch('mcpgateway.services.sso_service.create_jwt_token') as mock_jwt:
                            mock_jwt.return_value = "mock_token"

                            result = await sso_service.authenticate_or_create_user(user_info)

                            assert result == "mock_token"  # Token returned for approved user
                            mock_auth_service.create_user.assert_called_once()
                            mock_pending.status = "completed"  # Approval marked as used

    @pytest.mark.asyncio
    async def test_rejected_user_denied(self, sso_service):
        """Test that rejected users are denied access."""
        user_info = {
            "email": "rejected@example.com",
            "full_name": "Rejected User",
            "provider": "github"
        }

        # Mock settings to require approval
        with patch('mcpgateway.services.sso_service.settings') as mock_settings:
            mock_settings.sso_require_admin_approval = True

            # Mock existing rejected pending approval
            mock_pending = MagicMock()
            mock_pending.status = "rejected"
            sso_service.db.execute.return_value.scalar_one_or_none.return_value = mock_pending

            # Mock get_user_by_email to return None (new user)
            with patch.object(sso_service, 'auth_service') as mock_auth_service:
                # For async methods, need to use AsyncMock
                mock_auth_service.get_user_by_email = AsyncMock(return_value=None)

                # Mock get_provider
                with patch.object(sso_service, 'get_provider') as mock_get_provider:
                    mock_provider = MagicMock()
                    mock_provider.auto_create_users = True
                    mock_provider.trusted_domains = []
                    mock_get_provider.return_value = mock_provider

                    # Should return None (access denied)
                    result = await sso_service.authenticate_or_create_user(user_info)

                    assert result is None  # Access denied for rejected user

    def test_pending_approval_model_methods(self):
        """Test PendingUserApproval model methods."""
        # Test approval
        approval = PendingUserApproval(
            email="test@example.com",
            full_name="Test User",
            auth_provider="github",
            expires_at=utc_now() + timedelta(days=30)
        )

        approval.approve("admin@example.com", "Looks good")
        assert approval.status == "approved"
        assert approval.approved_by == "admin@example.com"
        assert approval.admin_notes == "Looks good"
        assert approval.approved_at is not None

        # Test rejection
        approval2 = PendingUserApproval(
            email="test2@example.com",
            full_name="Test User 2",
            auth_provider="google",
            expires_at=utc_now() + timedelta(days=30)
        )

        approval2.reject("admin@example.com", "Suspicious activity", "Account flagged")
        assert approval2.status == "rejected"
        assert approval2.approved_by == "admin@example.com"
        assert approval2.rejection_reason == "Suspicious activity"
        assert approval2.admin_notes == "Account flagged"
        assert approval2.approved_at is not None
