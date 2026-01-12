# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_tokens.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for JWT Token Catalog API endpoints.
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
import pytest
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.routers.tokens import (
    _require_interactive_session,
    admin_revoke_token,
    create_team_token,
    create_token,
    get_token,
    get_token_usage_stats,
    list_all_tokens,
    list_team_tokens,
    list_tokens,
    revoke_token,
    update_token,
)
from mcpgateway.schemas import (
    TokenCreateRequest,
    TokenCreateResponse,
    TokenListResponse,
    TokenResponse,
    TokenRevokeRequest,
    TokenUpdateRequest,
    TokenUsageStatsResponse,
)
from mcpgateway.services.token_catalog_service import TokenScope

# Test utilities
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
def mock_current_user(mock_db):
    """Create a mock current user with db context."""
    return {
        "email": "test@example.com",
        "is_admin": False,
        "permissions": ["tokens.create", "tokens.read"],
        "db": mock_db,  # Include db in user context for RBAC decorator
        "auth_method": "jwt",  # Required for interactive session check
    }


@pytest.fixture
def mock_admin_user(mock_db):
    """Create a mock admin user with db context."""
    return {
        "email": "admin@example.com",
        "is_admin": True,
        "permissions": ["*"],
        "db": mock_db,  # Include db in user context for RBAC decorator
        "auth_method": "jwt",  # Required for interactive session check
    }


@pytest.fixture
def mock_token_record():
    """Create a mock token record."""
    token = MagicMock()
    token.id = "token-123"
    token.name = "Test Token"
    token.description = "Test description"
    token.user_email = "test@example.com"
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


class TestInteractiveSessionGate:
    """Test interactive session gating for token endpoints."""

    def test_api_token_blocked(self):
        """API tokens are blocked from token management."""
        with pytest.raises(HTTPException) as exc_info:
            _require_interactive_session({"auth_method": "api_token"})

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    def test_missing_auth_method_blocked(self):
        """Missing auth_method fails secure."""
        with pytest.raises(HTTPException) as exc_info:
            _require_interactive_session({})

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    def test_oauth_allowed(self):
        """SSO/OAuth sessions are allowed."""
        _require_interactive_session({"auth_method": "oauth"})

    def test_disabled_allowed(self):
        """auth_disabled mode is allowed."""
        _require_interactive_session({"auth_method": "disabled"})


class TestCreateToken:
    """Test cases for create_token endpoint."""

    @pytest.mark.asyncio
    async def test_create_token_success(self, mock_db, mock_current_user, mock_token_record):
        """Test successful token creation."""
        request = TokenCreateRequest(
            name="Test Token",
            description="Test description",
            expires_in_days=30,
            tags=["test"],
        )

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.create_token = AsyncMock(return_value=(mock_token_record, "raw-token-string"))

            response = await create_token(request, current_user=mock_current_user, db=mock_db)

            assert isinstance(response, TokenCreateResponse)
            assert response.access_token == "raw-token-string"
            assert response.token.name == "Test Token"
            mock_service.create_token.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_token_with_scope(self, mock_db, mock_current_user, mock_token_record):
        """Test token creation with scope restrictions."""
        scope_data = {
            "server_id": "server-123",
            "permissions": ["tools.read", "tools.write"],
            "ip_restrictions": ["192.168.1.0/24"],
            "time_restrictions": {"start_time": "09:00", "end_time": "17:00"},
            "usage_limits": {"max_calls": 1000},
        }
        request = TokenCreateRequest(
            name="Scoped Token",
            description="Token with scope",
            scope=scope_data,
            expires_in_days=30,
        )

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.create_token = AsyncMock(return_value=(mock_token_record, "scoped-token"))

            response = await create_token(request, current_user=mock_current_user, db=mock_db)

            assert response.access_token == "scoped-token"
            # Verify scope was created and passed
            call_args = mock_service.create_token.call_args
            assert call_args[1]["scope"] is not None
            assert isinstance(call_args[1]["scope"], TokenScope)

    @pytest.mark.asyncio
    async def test_create_token_value_error(self, mock_db, mock_current_user):
        """Test token creation with validation error."""
        request = TokenCreateRequest(
            name="Invalid Token",
            description="Test",
        )

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.create_token = AsyncMock(side_effect=ValueError("Token name already exists"))

            with pytest.raises(HTTPException) as exc_info:
                await create_token(request, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
            assert "Token name already exists" in str(exc_info.value.detail)


class TestListTokens:
    """Test cases for list_tokens endpoint."""

    @pytest.mark.asyncio
    async def test_list_tokens_success(self, mock_db, mock_current_user, mock_token_record):
        """Test successful token listing."""
        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.list_user_tokens = AsyncMock(return_value=[mock_token_record])
            mock_service.get_token_revocation = AsyncMock(return_value=None)

            response = await list_tokens(include_inactive=False, limit=50, offset=0, db=mock_db, current_user=mock_current_user)

            assert isinstance(response, TokenListResponse)
            assert len(response.tokens) == 1
            assert response.tokens[0].name == "Test Token"
            assert response.total == 1
            assert response.limit == 50
            assert response.offset == 0

    @pytest.mark.asyncio
    async def test_list_tokens_with_revoked(self, mock_db, mock_current_user, mock_token_record):
        """Test listing tokens with revoked token."""
        revocation_info = MagicMock()
        revocation_info.revoked_at = datetime.now(timezone.utc)
        revocation_info.revoked_by = "admin@example.com"
        revocation_info.reason = "Security concern"

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.list_user_tokens = AsyncMock(return_value=[mock_token_record])
            mock_service.get_token_revocation = AsyncMock(return_value=revocation_info)

            response = await list_tokens(include_inactive=True, limit=10, offset=0, db=mock_db, current_user=mock_current_user)

            assert len(response.tokens) == 1
            assert response.tokens[0].is_revoked is True
            assert response.tokens[0].revoked_by == "admin@example.com"
            assert response.tokens[0].revocation_reason == "Security concern"

    @pytest.mark.asyncio
    async def test_list_tokens_pagination(self, mock_db, mock_current_user):
        """Test token listing with pagination."""
        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.list_user_tokens = AsyncMock(return_value=[])
            mock_service.get_token_revocation = AsyncMock(return_value=None)

            response = await list_tokens(include_inactive=False, limit=20, offset=10, db=mock_db, current_user=mock_current_user)

            assert response.tokens == []
            assert response.limit == 20
            assert response.offset == 10
            mock_service.list_user_tokens.assert_called_with(
                user_email="test@example.com",
                include_inactive=False,
                limit=20,
                offset=10,
            )


class TestGetToken:
    """Test cases for get_token endpoint."""

    @pytest.mark.asyncio
    async def test_get_token_success(self, mock_db, mock_current_user, mock_token_record):
        """Test successful token retrieval."""
        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.get_token = AsyncMock(return_value=mock_token_record)

            response = await get_token(token_id="token-123", current_user=mock_current_user, db=mock_db)

            assert isinstance(response, TokenResponse)
            assert response.id == "token-123"
            assert response.name == "Test Token"

    @pytest.mark.asyncio
    async def test_get_token_not_found(self, mock_db, mock_current_user):
        """Test token not found."""
        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.get_token = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await get_token(token_id="nonexistent", current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
            assert "Token not found" in str(exc_info.value.detail)


class TestUpdateToken:
    """Test cases for update_token endpoint."""

    @pytest.mark.asyncio
    async def test_update_token_success(self, mock_db, mock_current_user, mock_token_record):
        """Test successful token update."""
        request = TokenUpdateRequest(
            name="Updated Token",
            description="Updated description",
            tags=["updated"],
        )

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_token_record.name = "Updated Token"
            mock_token_record.description = "Updated description"
            mock_service.update_token = AsyncMock(return_value=mock_token_record)

            response = await update_token(token_id="token-123", request=request, current_user=mock_current_user, db=mock_db)

            assert response.name == "Updated Token"
            assert response.description == "Updated description"

    @pytest.mark.asyncio
    async def test_update_token_with_scope(self, mock_db, mock_current_user, mock_token_record):
        """Test token update with new scope."""
        scope_data = {
            "server_id": "new-server",
            "permissions": ["tools.admin"],
        }
        request = TokenUpdateRequest(
            name="Updated Token",
            scope=scope_data,
        )

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class, patch("mcpgateway.routers.tokens._get_caller_permissions", new_callable=AsyncMock) as mock_perms:
            mock_service = mock_service_class.return_value
            mock_service.get_token = AsyncMock(return_value=mock_token_record)  # For scope containment lookup
            mock_service.update_token = AsyncMock(return_value=mock_token_record)
            mock_perms.return_value = ["tools.admin"]  # Return sufficient permissions

            response = await update_token(token_id="token-123", request=request, current_user=mock_current_user, db=mock_db)

            call_args = mock_service.update_token.call_args
            assert call_args[1]["scope"] is not None
            assert isinstance(call_args[1]["scope"], TokenScope)

    @pytest.mark.asyncio
    async def test_update_token_not_found(self, mock_db, mock_current_user):
        """Test updating non-existent token."""
        request = TokenUpdateRequest(name="Updated")

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.update_token = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await update_token(token_id="nonexistent", request=request, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_update_token_validation_error(self, mock_db, mock_current_user):
        """Test token update with validation error."""
        request = TokenUpdateRequest(name="Invalid@Name")

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.update_token = AsyncMock(side_effect=ValueError("Invalid token name"))

            with pytest.raises(HTTPException) as exc_info:
                await update_token(token_id="token-123", request=request, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
            assert "Invalid token name" in str(exc_info.value.detail)


class TestRevokeToken:
    """Test cases for revoke_token endpoint."""

    @pytest.mark.asyncio
    async def test_revoke_token_success(self, mock_db, mock_current_user):
        """Test successful token revocation."""
        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.revoke_token = AsyncMock(return_value=True)

            await revoke_token(token_id="token-123", request=None, current_user=mock_current_user, db=mock_db)

            mock_service.revoke_token.assert_called_with(
                token_id="token-123",
                user_email="test@example.com",
                revoked_by="test@example.com",
                reason="Revoked by user",
            )

    @pytest.mark.asyncio
    async def test_revoke_token_with_reason(self, mock_db, mock_current_user):
        """Test token revocation with custom reason."""
        request = TokenRevokeRequest(reason="Security breach")

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.revoke_token = AsyncMock(return_value=True)

            await revoke_token(token_id="token-123", request=request, current_user=mock_current_user, db=mock_db)

            mock_service.revoke_token.assert_called_with(
                token_id="token-123",
                user_email="test@example.com",
                revoked_by="test@example.com",
                reason="Security breach",
            )

    @pytest.mark.asyncio
    async def test_revoke_token_not_found(self, mock_db, mock_current_user):
        """Test revoking non-existent token."""
        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.revoke_token = AsyncMock(return_value=False)

            with pytest.raises(HTTPException) as exc_info:
                await revoke_token(token_id="nonexistent", request=None, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


class TestGetTokenUsageStats:
    """Test cases for get_token_usage_stats endpoint."""

    @pytest.mark.asyncio
    async def test_get_usage_stats_success(self, mock_db, mock_current_user, mock_token_record):
        """Test successful usage stats retrieval."""
        stats_data = {
            "period_days": 30,
            "total_requests": 500,
            "successful_requests": 480,
            "blocked_requests": 20,
            "success_rate": 0.96,
            "average_response_time_ms": 250.5,
            "top_endpoints": [("/api/test", 300), ("/api/data", 200)],
        }

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.get_token = AsyncMock(return_value=mock_token_record)
            mock_service.get_token_usage_stats = AsyncMock(return_value=stats_data)

            response = await get_token_usage_stats(token_id="token-123", days=30, current_user=mock_current_user, db=mock_db)

            assert isinstance(response, TokenUsageStatsResponse)
            assert response.period_days == 30
            assert response.total_requests == 500
            assert response.successful_requests == 480
            assert response.blocked_requests == 20
            assert response.success_rate == 0.96
            assert response.average_response_time_ms == 250.5

    @pytest.mark.asyncio
    async def test_get_usage_stats_token_not_found(self, mock_db, mock_current_user):
        """Test usage stats for non-existent token."""
        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.get_token = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await get_token_usage_stats(token_id="nonexistent", days=30, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


class TestAdminEndpoints:
    """Test cases for admin endpoints."""

    @pytest.mark.asyncio
    async def test_list_all_tokens_admin(self, mock_db, mock_admin_user, mock_token_record):
        """Test admin listing all tokens."""
        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.list_user_tokens = AsyncMock(return_value=[mock_token_record])
            mock_service.get_token_revocation = AsyncMock(return_value=None)

            response = await list_all_tokens(user_email="user@example.com", include_inactive=False, limit=100, offset=0, current_user=mock_admin_user, db=mock_db)

            assert isinstance(response, TokenListResponse)
            assert len(response.tokens) == 1

    @pytest.mark.asyncio
    async def test_list_all_tokens_non_admin(self, mock_db, mock_current_user):
        """Test non-admin trying to list all tokens."""
        with pytest.raises(HTTPException) as exc_info:
            await list_all_tokens(user_email=None, include_inactive=False, limit=100, offset=0, current_user=mock_current_user, db=mock_db)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Admin access required" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_admin_revoke_token_success(self, mock_db, mock_admin_user):
        """Test admin revoking any token."""
        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.admin_revoke_token = AsyncMock(return_value=True)

            await admin_revoke_token(token_id="token-123", request=None, current_user=mock_admin_user, db=mock_db)

            mock_service.admin_revoke_token.assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_revoke_token_blocked_for_api_token(self, mock_db, mock_admin_user):
        """Admin API tokens are blocked from admin endpoints."""
        current_user = dict(mock_admin_user)
        current_user["auth_method"] = "api_token"

        with pytest.raises(HTTPException) as exc_info:
            await admin_revoke_token(token_id="token-123", request=None, current_user=current_user, db=mock_db)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_admin_revoke_token_non_admin(self, mock_db, mock_current_user):
        """Test non-admin trying to use admin revoke."""
        with pytest.raises(HTTPException) as exc_info:
            await admin_revoke_token(token_id="token-123", request=None, current_user=mock_current_user, db=mock_db)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_admin_revoke_token_not_found(self, mock_db, mock_admin_user):
        """Test admin revoking non-existent token."""
        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.admin_revoke_token = AsyncMock(return_value=False)

            with pytest.raises(HTTPException) as exc_info:
                await admin_revoke_token(token_id="nonexistent", request=None, current_user=mock_admin_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


class TestTeamTokens:
    """Test cases for team token endpoints."""

    @pytest.mark.asyncio
    async def test_create_team_token_success(self, mock_db, mock_current_user, mock_token_record):
        """Test creating a team token."""
        request = TokenCreateRequest(
            name="Team Token",
            description="Token for team",
            expires_in_days=90,
        )
        mock_token_record.team_id = "team-456"

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.create_token = AsyncMock(return_value=(mock_token_record, "team-token-raw"))

            response = await create_team_token(team_id="team-456", request=request, current_user=mock_current_user, db=mock_db)

            assert response.access_token == "team-token-raw"
            assert response.token.team_id == "team-456"

            # Verify team_id was passed
            call_args = mock_service.create_token.call_args
            assert call_args[1]["team_id"] == "team-456"

    @pytest.mark.asyncio
    async def test_create_team_token_validation_error(self, mock_db, mock_current_user):
        """Test team token creation with validation error."""
        request = TokenCreateRequest(name="Invalid")

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.create_token = AsyncMock(side_effect=ValueError("User is not team owner"))

            with pytest.raises(HTTPException) as exc_info:
                await create_team_token(team_id="team-456", request=request, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
            assert "User is not team owner" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_list_team_tokens_success(self, mock_db, mock_current_user, mock_token_record):
        """Test listing team tokens."""
        mock_token_record.team_id = "team-456"

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.list_team_tokens = AsyncMock(return_value=[mock_token_record])
            mock_service.get_token_revocation = AsyncMock(return_value=None)

            response = await list_team_tokens(team_id="team-456", include_inactive=False, limit=50, offset=0, current_user=mock_current_user, db=mock_db)

            assert len(response.tokens) == 1
            assert response.tokens[0].team_id == "team-456"

    @pytest.mark.asyncio
    async def test_list_team_tokens_unauthorized(self, mock_db, mock_current_user):
        """Test listing team tokens without ownership."""
        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.list_team_tokens = AsyncMock(side_effect=ValueError("User is not team member"))

            with pytest.raises(HTTPException) as exc_info:
                await list_team_tokens(team_id="team-456", include_inactive=False, limit=50, offset=0, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
            assert "User is not team member" in str(exc_info.value.detail)


class TestEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_create_token_with_team_id_in_request(self, mock_db, mock_current_user, mock_token_record):
        """Test token creation with team_id in request object."""
        request = MagicMock(spec=TokenCreateRequest)
        request.name = "Team Token"
        request.description = "Test"
        request.scope = None
        request.expires_in_days = 30
        request.tags = []
        request.team_id = "team-789"  # Add team_id attribute

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.create_token = AsyncMock(return_value=(mock_token_record, "token-with-team"))

            response = await create_token(request, current_user=mock_current_user, db=mock_db)

            # Verify team_id was passed from request
            call_args = mock_service.create_token.call_args
            assert call_args[1]["team_id"] == "team-789"

    @pytest.mark.asyncio
    async def test_list_tokens_empty_result(self, mock_db, mock_current_user):
        """Test listing tokens with no results."""
        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.list_user_tokens = AsyncMock(return_value=[])

            response = await list_tokens(include_inactive=True, limit=100, offset=50, db=mock_db, current_user=mock_current_user)

            assert response.tokens == []
            assert response.total == 0
            assert response.limit == 100
            assert response.offset == 50

    @pytest.mark.asyncio
    async def test_admin_list_all_tokens_no_email(self, mock_db, mock_admin_user):
        """Test admin listing all tokens without email filter."""
        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value

            response = await list_all_tokens(user_email=None, include_inactive=False, limit=100, offset=0, current_user=mock_admin_user, db=mock_db)

            # Currently returns empty list when no email provided
            assert response.tokens == []
            assert response.total == 0

    @pytest.mark.asyncio
    async def test_create_token_with_complex_scope(self, mock_db, mock_current_user, mock_token_record):
        """Test token creation with all scope fields."""
        scope_data = {
            "server_id": "srv-123",
            "permissions": ["tools.read", "tools.write", "tools.delete"],
            "ip_restrictions": ["192.168.1.0/24", "10.0.0.0/8"],
            "time_restrictions": {"start_time": "08:00", "end_time": "18:00", "timezone": "UTC", "days": ["mon", "tue", "wed", "thu", "fri"]},
            "usage_limits": {"max_calls": 10000, "max_bytes": 1048576, "rate_limit": "100/hour"},
        }
        request = TokenCreateRequest(
            name="Complex Token",
            description="Token with full scope",
            scope=scope_data,
            expires_in_days=365,
            tags=["production", "api", "restricted"],
        )

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.create_token = AsyncMock(return_value=(mock_token_record, "complex-token"))

            response = await create_token(request, current_user=mock_current_user, db=mock_db)

            assert response.access_token == "complex-token"

            # Verify complex scope was properly created
            call_args = mock_service.create_token.call_args
            scope = call_args[1]["scope"]
            assert scope.server_id == "srv-123"
            assert len(scope.permissions) == 3
            assert len(scope.ip_restrictions) == 2
            assert scope.usage_limits["max_calls"] == 10000
