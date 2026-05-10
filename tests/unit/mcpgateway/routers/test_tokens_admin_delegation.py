# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_tokens_admin_delegation.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for admin-delegated token creation feature.
Tests the user_email parameter in POST /tokens endpoint.
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException, status
import pytest
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.routers.tokens import create_team_token, create_token
from mcpgateway.schemas import TokenCreateRequest, TokenCreateResponse

# Local
from tests.utils.rbac_mocks import patch_rbac_decorators, restore_rbac_decorators


@pytest.fixture(autouse=True)
def setup_rbac_mocks():
    """Setup and teardown RBAC mocks for each test."""
    originals = patch_rbac_decorators()
    yield
    restore_rbac_decorators(originals)


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    return MagicMock(spec=Session)


@pytest.fixture
def mock_regular_user(mock_db):
    """Create a mock regular user."""
    return {
        "email": "user@example.com",
        "is_admin": False,
        "permissions": ["tokens.create", "tokens.read"],
        "db": mock_db,
        "auth_method": "jwt",
        "token_teams": ["team-1"],
    }


@pytest.fixture
def mock_admin_user(mock_db):
    """Create a mock un-narrowed admin user."""
    return {
        "email": "admin@example.com",
        "is_admin": True,
        "permissions": ["*"],
        "db": mock_db,
        "auth_method": "jwt",
        "token_teams": None,  # Un-narrowed admin
    }


@pytest.fixture
def mock_narrowed_admin_user(mock_db):
    """Create a mock narrowed admin user."""
    return {
        "email": "narrowed-admin@example.com",
        "is_admin": True,
        "permissions": ["*"],
        "db": mock_db,
        "auth_method": "jwt",
        "token_teams": ["team-1"],  # Narrowed to specific team
    }


@pytest.fixture
def mock_unauthenticated_user(mock_db):
    """Create a mock unauthenticated user."""
    return {
        "email": None,
        "is_admin": False,
        "permissions": [],
        "db": mock_db,
        "auth_method": None,
        "token_teams": [],
    }


@pytest.fixture
def mock_token_record():
    """Create a mock token record."""
    token = MagicMock()
    token.id = "token-123"
    token.name = "Test Token"
    token.description = "Test description"
    token.user_email = "target@example.com"
    token.team_id = None
    token.server_id = None
    token.resource_scopes = []
    token.ip_restrictions = []
    token.time_restrictions = {}
    token.usage_limits = {}
    token.created_at = datetime.now(timezone.utc)
    token.expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    token.last_used = None
    token.is_active = True
    token.tags = ["test"]
    token.jti = "jti-123"
    return token


class TestAdminDelegatedTokenCreation:
    """Test cases for admin-delegated token creation with user_email parameter."""

    @pytest.mark.asyncio
    async def test_create_token_for_self_without_user_email(self, mock_db, mock_regular_user, mock_token_record):
        """Regular user creates token for themselves (no user_email specified)."""
        request = TokenCreateRequest(
            name="My Token",
            description="Token for myself",
            expires_in_days=30,
        )
        mock_token_record.user_email = mock_regular_user["email"]

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.create_token = AsyncMock(return_value=(mock_token_record, "raw-token"))

            response = await create_token(request, current_user=mock_regular_user, db=mock_db)

            assert isinstance(response, TokenCreateResponse)
            assert response.token.user_email == mock_regular_user["email"]
            # Verify service was called with current user's email
            call_args = mock_service.create_token.call_args
            assert call_args[1]["user_email"] == mock_regular_user["email"]

    @pytest.mark.asyncio
    async def test_admin_creates_token_for_other_user(self, mock_db, mock_admin_user, mock_token_record):
        """Un-narrowed admin creates token for another user."""
        target_email = "target@example.com"
        request = TokenCreateRequest(
            name="Delegated Token",
            description="Token for another user",
            user_email=target_email,
            expires_in_days=30,
        )
        mock_token_record.user_email = target_email

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.create_token = AsyncMock(return_value=(mock_token_record, "delegated-token"))

            response = await create_token(request, current_user=mock_admin_user, db=mock_db)

            assert isinstance(response, TokenCreateResponse)
            assert response.token.user_email == target_email
            # Verify service was called with target user's email
            call_args = mock_service.create_token.call_args
            assert call_args[1]["user_email"] == target_email

    @pytest.mark.asyncio
    async def test_regular_user_cannot_create_token_for_other_user(self, mock_db, mock_regular_user):
        """Regular user cannot create token for another user (403 Forbidden)."""
        request = TokenCreateRequest(
            name="Unauthorized Token",
            description="Trying to create for someone else",
            user_email="other@example.com",
            expires_in_days=30,
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_token(request, current_user=mock_regular_user, db=mock_db)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Admin access required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_narrowed_admin_cannot_create_token_for_other_user(self, mock_db, mock_narrowed_admin_user):
        """Narrowed admin cannot create token for another user (403 Forbidden)."""
        request = TokenCreateRequest(
            name="Narrowed Admin Token",
            description="Narrowed admin trying to delegate",
            user_email="target@example.com",
            expires_in_days=30,
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_token(request, current_user=mock_narrowed_admin_user, db=mock_db)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "un-narrowed admin access" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_admin_creates_token_for_self_with_explicit_email(self, mock_db, mock_admin_user, mock_token_record):
        """Admin explicitly specifies their own email (should work)."""
        request = TokenCreateRequest(
            name="Admin Self Token",
            description="Admin creating for themselves explicitly",
            user_email=mock_admin_user["email"],
            expires_in_days=30,
        )
        mock_token_record.user_email = mock_admin_user["email"]

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.create_token = AsyncMock(return_value=(mock_token_record, "admin-self-token"))

            response = await create_token(request, current_user=mock_admin_user, db=mock_db)

            assert isinstance(response, TokenCreateResponse)
            assert response.token.user_email == mock_admin_user["email"]

    @pytest.mark.asyncio
    async def test_narrowed_admin_can_create_token_for_self(self, mock_db, mock_narrowed_admin_user, mock_token_record):
        """Narrowed admin can still create tokens for themselves."""
        request = TokenCreateRequest(
            name="Narrowed Admin Self Token",
            description="Narrowed admin creating for themselves",
            expires_in_days=30,
        )
        mock_token_record.user_email = mock_narrowed_admin_user["email"]

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.create_token = AsyncMock(return_value=(mock_token_record, "narrowed-self-token"))

            response = await create_token(request, current_user=mock_narrowed_admin_user, db=mock_db)

            assert isinstance(response, TokenCreateResponse)
            assert response.token.user_email == mock_narrowed_admin_user["email"]

    @pytest.mark.asyncio
    async def test_admin_delegation_preserves_audit_trail(self, mock_db, mock_admin_user, mock_token_record):
        """Admin-delegated token creation is logged for audit trail."""
        target_email = "audited@example.com"
        request = TokenCreateRequest(
            name="Audited Token",
            description="Token with audit trail",
            user_email=target_email,
            expires_in_days=30,
        )
        mock_token_record.user_email = target_email

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class, patch("mcpgateway.routers.tokens.logger") as mock_logger:
            mock_service = mock_service_class.return_value
            mock_service.create_token = AsyncMock(return_value=(mock_token_record, "audited-token"))

            await create_token(request, current_user=mock_admin_user, db=mock_db)

            # Verify audit log was created
            mock_logger.info.assert_any_call(
                "Admin %s creating token for user %s",
                mock_admin_user["email"],
                target_email,
            )

    @pytest.mark.asyncio
    async def test_unauthenticated_cannot_create_delegated_token(self, mock_db, mock_unauthenticated_user):
        """Unauthenticated user cannot create delegated token (403 Forbidden)."""
        request = TokenCreateRequest(
            name="Unauthorized Delegated Token",
            description="Unauthenticated trying to create for someone else",
            user_email="target@example.com",
            expires_in_days=30,
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_token(request, current_user=mock_unauthenticated_user, db=mock_db)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Token management requires authentication" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_case_insensitive_email_does_not_trigger_delegation(self, mock_db, mock_regular_user, mock_token_record):
        """Regular user passes their own email with different casing — should not trigger admin check."""
        request = TokenCreateRequest(
            name="My Token",
            description="Token for myself with different case",
            user_email="USER@example.com",
            expires_in_days=30,
        )
        mock_token_record.user_email = mock_regular_user["email"]

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.create_token = AsyncMock(return_value=(mock_token_record, "raw-token"))

            response = await create_token(request, current_user=mock_regular_user, db=mock_db)

            assert isinstance(response, TokenCreateResponse)
            # Verify service was called with current user's email (not the cased version)
            call_args = mock_service.create_token.call_args
            assert call_args[1]["user_email"] == mock_regular_user["email"]

    @pytest.mark.asyncio
    async def test_delegated_token_for_nonexistent_user_returns_400(self, mock_db, mock_admin_user):
        """Admin delegation for non-existent user returns 400 Bad Request."""
        request = TokenCreateRequest(
            name="Delegated Token",
            description="Token for non-existent user",
            user_email="nonexistent@example.com",
            expires_in_days=30,
        )

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.create_token = AsyncMock(side_effect=ValueError("User not found: nonexistent@example.com"))

            with pytest.raises(HTTPException) as exc_info:
                await create_token(request, current_user=mock_admin_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.asyncio
    async def test_admin_delegation_passes_caller_email_to_service(self, mock_db, mock_admin_user, mock_token_record):
        """Admin-delegated token creation passes caller_email to service for membership enforcement."""
        target_email = "target@example.com"
        request = TokenCreateRequest(
            name="Delegated Token",
            description="Token for another user",
            user_email=target_email,
            expires_in_days=30,
            team_id="team-123",
        )
        mock_token_record.user_email = target_email
        mock_token_record.team_id = "team-123"

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.create_token = AsyncMock(return_value=(mock_token_record, "delegated-token"))

            response = await create_token(request, current_user=mock_admin_user, db=mock_db)

            assert isinstance(response, TokenCreateResponse)
            call_args = mock_service.create_token.call_args
            assert call_args[1]["caller_email"] == mock_admin_user["email"]
            assert call_args[1]["user_email"] == target_email
            assert call_args[1]["team_id"] == "team-123"


class TestAdminDelegatedTeamTokenCreation:
    """Test cases for admin-delegated team token creation with user_email parameter."""

    @pytest.mark.asyncio
    async def test_admin_delegates_team_token_for_other_user(self, mock_db, mock_admin_user, mock_token_record):
        """Un-narrowed admin creates team token for another user via create_team_token."""
        target_email = "target@example.com"
        request = TokenCreateRequest(
            name="Delegated Team Token",
            description="Team token for another user",
            user_email=target_email,
            expires_in_days=30,
        )
        mock_token_record.user_email = target_email
        mock_token_record.team_id = "team-456"

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class, patch("mcpgateway.routers.tokens.logger") as mock_logger:
            mock_service = mock_service_class.return_value
            mock_service.create_token = AsyncMock(return_value=(mock_token_record, "delegated-team-token"))

            response = await create_team_token(team_id="team-456", request=request, current_user=mock_admin_user, db=mock_db)

            assert isinstance(response, TokenCreateResponse)
            assert response.token.user_email == target_email
            mock_logger.info.assert_any_call(
                "Admin %s creating team token for user %s",
                mock_admin_user["email"],
                target_email,
            )

    @pytest.mark.asyncio
    async def test_regular_user_cannot_delegate_team_token(self, mock_db, mock_regular_user):
        """Regular user cannot create team token for another user (403 Forbidden)."""
        request = TokenCreateRequest(
            name="Unauthorized Team Token",
            description="Trying to create team token for someone else",
            user_email="other@example.com",
            expires_in_days=30,
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_team_token(team_id="team-456", request=request, current_user=mock_regular_user, db=mock_db)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Admin access required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_narrowed_admin_cannot_delegate_team_token(self, mock_db, mock_narrowed_admin_user):
        """Narrowed admin cannot create team token for another user (403 Forbidden)."""
        request = TokenCreateRequest(
            name="Narrowed Admin Team Token",
            description="Narrowed admin trying to delegate team token",
            user_email="target@example.com",
            expires_in_days=30,
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_team_token(team_id="team-456", request=request, current_user=mock_narrowed_admin_user, db=mock_db)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "un-narrowed admin access" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_admin_team_token_for_self_with_explicit_email(self, mock_db, mock_admin_user, mock_token_record):
        """Admin explicitly specifies their own email in team token creation (should work)."""
        request = TokenCreateRequest(
            name="Admin Self Team Token",
            description="Admin creating team token for themselves explicitly",
            user_email=mock_admin_user["email"],
            expires_in_days=30,
        )
        mock_token_record.user_email = mock_admin_user["email"]
        mock_token_record.team_id = "team-456"

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.create_token = AsyncMock(return_value=(mock_token_record, "admin-self-team-token"))

            response = await create_team_token(team_id="team-456", request=request, current_user=mock_admin_user, db=mock_db)

            assert isinstance(response, TokenCreateResponse)
            assert response.token.user_email == mock_admin_user["email"]
