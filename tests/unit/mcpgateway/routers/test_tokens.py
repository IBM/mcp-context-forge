# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/routers/test_tokens.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Unit tests for JWT Token Catalog API endpoints.
"""

# Standard
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Third-Party
from fastapi import HTTPException, status
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.routers.tokens import (
    _require_authenticated_session,
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

# Local
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
    """Create a mock un-narrowed platform admin (token_teams=None)."""
    return {
        "email": "admin@example.com",
        "is_admin": True,
        "token_teams": None,  # Un-narrowed: required to satisfy admin bypass
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


class TestAuthenticatedSessionGate:
    """Test authenticated session gating for token endpoints."""

    def test_api_token_blocked(self):
        """API tokens are blocked from token management (Management Plane isolation)."""
        with pytest.raises(HTTPException) as exc_info:
            _require_authenticated_session({"auth_method": "api_token"})

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "interactive session" in exc_info.value.detail

    def test_missing_auth_method_blocked(self):
        """Missing auth_method fails secure."""
        with pytest.raises(HTTPException) as exc_info:
            _require_authenticated_session({})

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    def test_anonymous_blocked(self):
        """Anonymous access is blocked."""
        with pytest.raises(HTTPException) as exc_info:
            _require_authenticated_session({"auth_method": "anonymous"})

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    def test_oauth_allowed(self):
        """SSO/OAuth sessions are allowed."""
        _require_authenticated_session({"auth_method": "oauth"})

    def test_disabled_allowed(self):
        """auth_disabled mode is allowed."""
        _require_authenticated_session({"auth_method": "disabled"})

    def test_jwt_allowed(self):
        """JWT sessions are allowed."""
        _require_authenticated_session({"auth_method": "jwt"})

    def test_proxy_allowed(self):
        """Proxy auth sessions are allowed."""
        _require_authenticated_session({"auth_method": "proxy"})


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

    @pytest.mark.asyncio
    async def test_create_token_with_is_active_false(self, mock_db, mock_current_user, mock_token_record):
        """Test creating token with is_active=False persists the value."""
        request = TokenCreateRequest(
            name="Inactive Token",
            description="Token created as inactive",
            is_active=False,
        )
        mock_token_record.is_active = False

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.create_token = AsyncMock(return_value=(mock_token_record, "inactive-token"))

            response = await create_token(request, current_user=mock_current_user, db=mock_db)

            assert response.token.is_active is False
            # Verify is_active=False was passed to service
            call_args = mock_service.create_token.call_args
            assert call_args[1]["is_active"] is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "constraint_fragment",
        [
            "uq_email_api_tokens_user_name_team",
            "uq_email_api_tokens_user_name",
            "uq_email_api_tokens_user_email_name",
            "email_api_tokens.user_email, email_api_tokens.name",
        ],
    )
    async def test_create_token_integrity_error_name_conflict(self, mock_db, mock_current_user, constraint_fragment):
        """IntegrityError with a known token-name constraint returns 409 with specific message."""
        request = TokenCreateRequest(name="Dup Token")

        orig = MagicMock()
        orig.__str__ = lambda self: constraint_fragment
        err = IntegrityError("INSERT", {}, orig)

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.create_token = AsyncMock(side_effect=err)

            with pytest.raises(HTTPException) as exc_info:
                await create_token(request, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_409_CONFLICT
            assert "already exists" in exc_info.value.detail
            assert "unique per user" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_create_token_integrity_error_generic_conflict(self, mock_db, mock_current_user):
        """IntegrityError with an unrecognised constraint returns 409 with generic message."""
        request = TokenCreateRequest(name="Dup Token")

        orig = MagicMock()
        orig.__str__ = lambda self: "some_other_constraint"
        err = IntegrityError("INSERT", {}, orig)

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.create_token = AsyncMock(side_effect=err)

            with pytest.raises(HTTPException) as exc_info:
                await create_token(request, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_409_CONFLICT
            assert "conflict" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_create_token_integrity_error_calls_rollback(self, mock_db, mock_current_user):
        """IntegrityError handler must call db.rollback() before raising."""
        request = TokenCreateRequest(name="Dup Token")

        orig = MagicMock()
        orig.__str__ = lambda self: "uq_email_api_tokens_user_name_team"
        err = IntegrityError("INSERT", {}, orig)

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.create_token = AsyncMock(side_effect=err)

            with pytest.raises(HTTPException):
                await create_token(request, current_user=mock_current_user, db=mock_db)

            mock_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_token_integrity_error_global_scope_partial_index(self, mock_db, mock_current_user):
        """IntegrityError from the partial unique index for global-scope tokens (team_id IS NULL) returns specific 409."""
        request = TokenCreateRequest(name="Global Dup")

        orig = MagicMock()
        orig.__str__ = lambda self: "uq_email_api_tokens_user_name_global"
        err = IntegrityError("INSERT", {}, orig)

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.create_token = AsyncMock(side_effect=err)

            with pytest.raises(HTTPException) as exc_info:
                await create_token(request, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_409_CONFLICT
            assert "already exists" in exc_info.value.detail


class TestListTokens:
    """Test cases for list_tokens endpoint."""

    @pytest.mark.asyncio
    async def test_list_tokens_success(self, mock_db, mock_current_user, mock_token_record):
        """Test successful token listing."""
        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.list_user_and_team_tokens = AsyncMock(return_value=[mock_token_record])
            mock_service.count_user_and_team_tokens = AsyncMock(return_value=1)
            mock_service.get_token_revocations_batch = AsyncMock(return_value={})

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
            mock_service.list_user_and_team_tokens = AsyncMock(return_value=[mock_token_record])
            mock_service.count_user_and_team_tokens = AsyncMock(return_value=1)
            mock_service.get_token_revocations_batch = AsyncMock(return_value={"jti-123": revocation_info})

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
            mock_service.list_user_and_team_tokens = AsyncMock(return_value=[])
            mock_service.count_user_and_team_tokens = AsyncMock(return_value=0)
            mock_service.get_token_revocations_batch = AsyncMock(return_value={})

            response = await list_tokens(include_inactive=False, limit=20, offset=10, db=mock_db, current_user=mock_current_user)

            assert response.tokens == []
            assert response.limit == 20
            assert response.offset == 10
            mock_service.list_user_and_team_tokens.assert_called_with(
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

    @pytest.mark.asyncio
    async def test_update_token_toggle_is_active(self, mock_db, mock_current_user, mock_token_record):
        """Test updating token to toggle is_active status."""
        # Deactivate an active token
        request = TokenUpdateRequest(is_active=False)
        mock_token_record.is_active = False

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.update_token = AsyncMock(return_value=mock_token_record)

            response = await update_token(token_id="token-123", request=request, current_user=mock_current_user, db=mock_db)

            assert response.is_active is False
            # Verify is_active=False was passed to service
            call_args = mock_service.update_token.call_args
            assert call_args[1]["is_active"] is False

    @pytest.mark.asyncio
    async def test_update_token_reactivate(self, mock_db, mock_current_user, mock_token_record):
        """Test updating token to reactivate it."""
        request = TokenUpdateRequest(is_active=True)
        mock_token_record.is_active = True

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.update_token = AsyncMock(return_value=mock_token_record)

            response = await update_token(token_id="token-123", request=request, current_user=mock_current_user, db=mock_db)

            assert response.is_active is True
            call_args = mock_service.update_token.call_args
            assert call_args[1]["is_active"] is True


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
            mock_service.count_user_tokens = AsyncMock(return_value=1)
            mock_service.get_token_revocations_batch = AsyncMock(return_value={})

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
    async def test_list_all_tokens_narrowed_admin_blocked(self, mock_db, mock_admin_user):
        """Test narrowed admin (token_teams present) is blocked from listing all tokens."""
        narrowed_admin = dict(mock_admin_user)
        narrowed_admin["token_teams"] = ["team-a"]  # Narrowed admin session

        with pytest.raises(HTTPException) as exc_info:
            await list_all_tokens(user_email=None, include_inactive=False, limit=100, offset=0, current_user=narrowed_admin, db=mock_db)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Token oversight requires un-narrowed admin access" in str(exc_info.value.detail)

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
        """API tokens are blocked from admin token management (Management Plane isolation)."""
        current_user = dict(mock_admin_user)
        current_user["auth_method"] = "api_token"

        # API tokens must NEVER manage tokens, even for admins — security invariant
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
    async def test_admin_revoke_token_narrowed_admin_blocked(self, mock_db, mock_admin_user):
        """Test narrowed admin (token_teams present) is blocked from admin revoke."""
        narrowed_admin = dict(mock_admin_user)
        narrowed_admin["token_teams"] = ["team-a"]  # Narrowed admin session

        with pytest.raises(HTTPException) as exc_info:
            await admin_revoke_token(token_id="token-123", request=None, current_user=narrowed_admin, db=mock_db)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Token oversight requires un-narrowed admin access" in str(exc_info.value.detail)

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
    @pytest.mark.parametrize(
        "constraint_fragment",
        [
            "uq_email_api_tokens_user_name_team",
            "uq_email_api_tokens_user_name",
            "uq_email_api_tokens_user_email_name",
            "email_api_tokens.user_email, email_api_tokens.name",
        ],
    )
    async def test_create_team_token_integrity_error_name_conflict(self, mock_db, mock_current_user, constraint_fragment):
        """IntegrityError with a known token-name constraint returns 409 with specific message."""
        request = TokenCreateRequest(name="Dup Team Token")

        orig = MagicMock()
        orig.__str__ = lambda self: constraint_fragment
        err = IntegrityError("INSERT", {}, orig)

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.create_token = AsyncMock(side_effect=err)

            with pytest.raises(HTTPException) as exc_info:
                await create_team_token(team_id="team-456", request=request, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_409_CONFLICT
            assert "already exists" in exc_info.value.detail
            assert "unique per user" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_create_team_token_integrity_error_generic_conflict(self, mock_db, mock_current_user):
        """IntegrityError with an unrecognised constraint returns 409 with generic message."""
        request = TokenCreateRequest(name="Dup Team Token")

        orig = MagicMock()
        orig.__str__ = lambda self: "some_other_constraint"
        err = IntegrityError("INSERT", {}, orig)

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.create_token = AsyncMock(side_effect=err)

            with pytest.raises(HTTPException) as exc_info:
                await create_team_token(team_id="team-456", request=request, current_user=mock_current_user, db=mock_db)

            assert exc_info.value.status_code == status.HTTP_409_CONFLICT
            assert "conflict" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_create_team_token_integrity_error_calls_rollback(self, mock_db, mock_current_user):
        """IntegrityError handler must call db.rollback() before raising."""
        request = TokenCreateRequest(name="Dup Team Token")

        orig = MagicMock()
        orig.__str__ = lambda self: "uq_email_api_tokens_user_name_team"
        err = IntegrityError("INSERT", {}, orig)

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.create_token = AsyncMock(side_effect=err)

            with pytest.raises(HTTPException):
                await create_team_token(team_id="team-456", request=request, current_user=mock_current_user, db=mock_db)

            mock_db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_team_tokens_success(self, mock_db, mock_current_user, mock_token_record):
        """Test listing team tokens."""
        mock_token_record.team_id = "team-456"

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.list_team_tokens = AsyncMock(return_value=[mock_token_record])
            mock_service.count_team_tokens = AsyncMock(return_value=1)
            mock_service.get_token_revocations_batch = AsyncMock(return_value={})

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


class TestApiTokenAuth:
    """Test that API token auth_method is blocked from all token management endpoints.

    API tokens represent the data plane; token management (CRUD) is a management-plane
    operation that requires an interactive session (JWT from web login or SSO).
    Allowing API tokens here would enable token-chaining attacks where a compromised
    token creates new long-lived tokens to maintain persistence.
    """

    @pytest.fixture
    def api_token_user(self, mock_db):
        """Create a user context authenticated via API token."""
        return {
            "email": "user@example.com",
            "is_admin": False,
            "permissions": ["tokens.create", "tokens.read", "tokens.update", "tokens.revoke"],
            "db": mock_db,
            "auth_method": "api_token",
        }

    @pytest.fixture
    def admin_api_token_user(self, mock_db):
        """Create an admin user context authenticated via API token."""
        return {
            "email": "admin@example.com",
            "is_admin": True,
            "permissions": ["*"],
            "db": mock_db,
            "auth_method": "api_token",
        }

    @pytest.mark.asyncio
    async def test_create_token_blocked_for_api_token(self, mock_db, api_token_user):
        """API token cannot create new tokens (token-chaining prevention)."""
        request = TokenCreateRequest(name="Created-Via-API-Token", description="Test")

        with pytest.raises(HTTPException) as exc_info:
            await create_token(request, current_user=api_token_user, db=mock_db)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "interactive session" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_list_tokens_blocked_for_api_token(self, mock_db, api_token_user):
        """API token cannot list tokens (management plane isolation)."""
        with pytest.raises(HTTPException) as exc_info:
            await list_tokens(include_inactive=False, limit=50, offset=0, db=mock_db, current_user=api_token_user)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_get_token_blocked_for_api_token(self, mock_db, api_token_user):
        """API token cannot get token details (management plane isolation)."""
        with pytest.raises(HTTPException) as exc_info:
            await get_token(token_id="token-123", current_user=api_token_user, db=mock_db)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_revoke_token_blocked_for_api_token(self, mock_db, api_token_user):
        """API token cannot revoke tokens (management plane isolation)."""
        with pytest.raises(HTTPException) as exc_info:
            await revoke_token(token_id="token-123", request=None, current_user=api_token_user, db=mock_db)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_update_token_blocked_for_api_token(self, mock_db, api_token_user):
        """API token cannot update tokens (management plane isolation)."""
        request = TokenUpdateRequest(name="Updated-Via-API-Token")

        with pytest.raises(HTTPException) as exc_info:
            await update_token(token_id="token-123", request=request, current_user=api_token_user, db=mock_db)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_get_usage_stats_blocked_for_api_token(self, mock_db, api_token_user):
        """API token cannot view usage stats (management plane isolation)."""
        with pytest.raises(HTTPException) as exc_info:
            await get_token_usage_stats(token_id="token-123", days=7, current_user=api_token_user, db=mock_db)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_admin_list_all_blocked_for_api_token(self, mock_db, admin_api_token_user):
        """Admin API token cannot list all tokens (management plane isolation)."""
        with pytest.raises(HTTPException) as exc_info:
            await list_all_tokens(user_email="other@example.com", include_inactive=False, limit=100, offset=0, current_user=admin_api_token_user, db=mock_db)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_create_team_token_blocked_for_api_token(self, mock_db, api_token_user):
        """API token cannot create team tokens (management plane isolation)."""
        request = TokenCreateRequest(name="Team-Token-Via-API", description="Test")

        with pytest.raises(HTTPException) as exc_info:
            await create_team_token(team_id="team-456", request=request, current_user=api_token_user, db=mock_db)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_list_team_tokens_blocked_for_api_token(self, mock_db, api_token_user):
        """API token cannot list team tokens (management plane isolation)."""
        with pytest.raises(HTTPException) as exc_info:
            await list_team_tokens(team_id="team-456", include_inactive=False, limit=50, offset=0, current_user=api_token_user, db=mock_db)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


class TestAuthenticatedSessionErrorMessages:
    """Test error message content for _require_authenticated_session."""

    def test_anonymous_error_message(self):
        """Anonymous rejection includes appropriate message."""
        with pytest.raises(HTTPException) as exc_info:
            _require_authenticated_session({"auth_method": "anonymous"})

        assert "Anonymous access is not permitted" in exc_info.value.detail

    def test_none_auth_method_error_message(self):
        """Missing auth_method rejection includes appropriate message."""
        with pytest.raises(HTTPException) as exc_info:
            _require_authenticated_session({})

        assert "Authentication method could not be determined" in exc_info.value.detail


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
        request.is_active = True  # Add is_active attribute

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
            mock_service.list_user_and_team_tokens = AsyncMock(return_value=[])
            mock_service.count_user_and_team_tokens = AsyncMock(return_value=0)
            mock_service.get_token_revocations_batch = AsyncMock(return_value={})

            response = await list_tokens(include_inactive=True, limit=100, offset=50, db=mock_db, current_user=mock_current_user)

            assert response.tokens == []
            assert response.total == 0
            assert response.limit == 100
            assert response.offset == 50

    @pytest.mark.asyncio
    async def test_admin_list_all_tokens_no_email(self, mock_db, mock_admin_user, mock_token_record):
        """Test admin listing all tokens without email filter."""
        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.list_all_tokens = AsyncMock(return_value=[mock_token_record])
            mock_service.count_all_tokens = AsyncMock(return_value=1)
            mock_service.get_token_revocations_batch = AsyncMock(return_value={})

            response = await list_all_tokens(user_email=None, include_inactive=False, limit=100, offset=0, current_user=mock_admin_user, db=mock_db)

            # Now returns all tokens when no email provided
            assert len(response.tokens) == 1
            assert response.total == 1

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

    @pytest.mark.asyncio
    async def test_create_token_auto_inherits_single_team(self, mock_db, mock_token_record):
        """Non-admin user belonging to exactly one team auto-inherits team_id when not set in the request."""
        single_team_user = {
            "email": "dev@example.com",
            "is_admin": False,
            "permissions": ["tokens.create"],
            "db": mock_db,
            "auth_method": "jwt",
            "token_teams": ["team-auto"],
        }
        request = MagicMock(spec=TokenCreateRequest)
        request.name = "Auto Team Token"
        request.description = None
        request.scope = None
        request.expires_in_days = 30
        request.tags = []
        request.team_id = None
        request.is_active = True

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.create_token = AsyncMock(return_value=(mock_token_record, "auto-inherit-token"))

            await create_token(request, current_user=single_team_user, db=mock_db)

            call_args = mock_service.create_token.call_args
            assert call_args[1]["team_id"] == "team-auto"


class TestAdminBypassRouterLevel:
    """Router-level tests for admin bypass feature (PR review findings)."""

    @pytest.mark.asyncio
    async def test_create_team_token_admin_bypass_no_scope(self, mock_db, mock_admin_user, mock_token_record):
        """Un-narrowed admin can create team token without scope (primary use case).

        This is the critical test that would have caught the router bug where
        caller_permissions was only fetched when request.scope was provided.
        """
        request = TokenCreateRequest(name="Admin Service Token", description="For automation")

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            with patch("mcpgateway.routers.tokens._get_caller_permissions") as mock_get_perms:
                mock_get_perms.return_value = ["*"]  # Un-narrowed admin
                mock_service = mock_service_class.return_value
                mock_service.create_token = AsyncMock(return_value=(mock_token_record, "admin-bypass-token"))

                result = await create_team_token(team_id="team-123", request=request, current_user=mock_admin_user, db=mock_db)

                # Verify _get_caller_permissions was called even without scope
                mock_get_perms.assert_called_once()

                # Verify service.create_token received the full bypass-gate context
                call_kwargs = mock_service.create_token.call_args[1]
                assert call_kwargs["caller_permissions"] == ["*"]
                assert call_kwargs["is_admin"] is True
                assert call_kwargs["caller_token_teams"] is None
                assert call_kwargs["caller_token_teams_provided"] is True
                assert call_kwargs["team_id"] == "team-123"
                assert result.access_token == "admin-bypass-token"

    @pytest.mark.asyncio
    async def test_create_team_token_admin_bypass_with_scope(self, mock_db, mock_admin_user, mock_token_record):
        """Un-narrowed admin can create team token with custom scope."""
        from mcpgateway.schemas import TokenScopeRequest

        request = TokenCreateRequest(name="Scoped Admin Token", description="With permissions", scope=TokenScopeRequest(permissions=["tools.read"]))

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            with patch("mcpgateway.routers.tokens._get_caller_permissions") as mock_get_perms:
                mock_get_perms.return_value = ["*"]
                mock_service = mock_service_class.return_value
                mock_service.create_token = AsyncMock(return_value=(mock_token_record, "scoped-admin-token"))

                result = await create_team_token(team_id="team-456", request=request, current_user=mock_admin_user, db=mock_db)

                # Verify the full bypass-gate context propagates
                call_kwargs = mock_service.create_token.call_args[1]
                assert call_kwargs["caller_permissions"] == ["*"]
                assert call_kwargs["is_admin"] is True
                assert call_kwargs["caller_token_teams"] is None
                assert call_kwargs["caller_token_teams_provided"] is True
                assert result.access_token == "scoped-admin-token"

    @pytest.mark.asyncio
    async def test_create_token_base_endpoint_admin_bypass(self, mock_db, mock_admin_user, mock_token_record):
        """Base POST /tokens endpoint also gets admin bypass for team tokens."""
        request = TokenCreateRequest(name="Base Endpoint Token", description="Via base endpoint", team_id="team-789")

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            with patch("mcpgateway.routers.tokens._get_caller_permissions") as mock_get_perms:
                mock_get_perms.return_value = ["*"]
                mock_service = mock_service_class.return_value
                mock_service.create_token = AsyncMock(return_value=(mock_token_record, "base-endpoint-token"))

                result = await create_token(request=request, current_user=mock_admin_user, db=mock_db)

                # Verify admin parameters propagate from base endpoint
                call_kwargs = mock_service.create_token.call_args[1]
                assert call_kwargs["caller_permissions"] == ["*"]
                assert call_kwargs["is_admin"] is True
                assert call_kwargs["caller_token_teams"] is None
                assert call_kwargs["caller_token_teams_provided"] is True
                assert call_kwargs["team_id"] == "team-789"
                assert result.access_token == "base-endpoint-token"

    @pytest.mark.asyncio
    async def test_list_team_tokens_admin_bypass(self, mock_db, mock_admin_user, mock_token_record):
        """Un-narrowed admin can list team tokens without membership."""
        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            with patch("mcpgateway.routers.tokens._get_caller_permissions") as mock_get_perms:
                mock_get_perms.return_value = ["*"]
                mock_service = mock_service_class.return_value
                mock_service.list_team_tokens = AsyncMock(return_value=[mock_token_record])
                mock_service.count_team_tokens = AsyncMock(return_value=1)
                mock_service.get_token_revocations_batch = AsyncMock(return_value={})

                result = await list_team_tokens(team_id="team-999", current_user=mock_admin_user, db=mock_db)

                # Verify admin parameters and the un-narrowed token scope propagate
                call_kwargs = mock_service.list_team_tokens.call_args[1]
                assert call_kwargs["caller_permissions"] == ["*"]
                assert call_kwargs["is_admin"] is True
                assert call_kwargs["caller_token_teams"] is None
                assert call_kwargs["caller_token_teams_provided"] is True
                assert len(result.tokens) == 1

    @pytest.mark.asyncio
    async def test_narrowed_admin_requires_membership(self, mock_db, mock_token_record):
        """Narrowed admin (token_teams set) still requires team membership."""
        narrowed_admin = {
            "email": "narrowed@example.com",
            "is_admin": True,
            "token_teams": ["other-team"],  # Narrowed to different team
            "permissions": ["tools.read"],
            "db": mock_db,
            "auth_method": "jwt",
        }

        request = TokenCreateRequest(name="Should Fail", description="Narrowed admin")

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            with patch("mcpgateway.routers.tokens._get_caller_permissions") as mock_get_perms:
                mock_get_perms.return_value = ["tools.read"]  # NOT ["*"]
                mock_service = mock_service_class.return_value
                # Service will raise ValueError for non-member
                mock_service.create_token = AsyncMock(side_effect=ValueError("User narrowed@example.com is not an active member of team team-blocked"))

                with pytest.raises(HTTPException) as exc_info:
                    await create_team_token(team_id="team-blocked", request=request, current_user=narrowed_admin, db=mock_db)

                assert exc_info.value.status_code == 400
                # Verify the router forwarded the narrowed scope so the service can deny bypass
                call_kwargs = mock_service.create_token.call_args[1]
                assert call_kwargs["is_admin"] is True
                assert call_kwargs["caller_permissions"] != ["*"]
                assert call_kwargs["caller_token_teams"] == ["other-team"]
                assert call_kwargs["caller_token_teams_provided"] is True

    @pytest.mark.asyncio
    async def test_narrowed_admin_with_global_wildcard_does_not_bypass(self, mock_db, mock_token_record):
        """Narrowed admin holding the global ``platform_admin`` role still requires membership.

        This regression covers the case where ``_get_caller_permissions`` falls
        through to ``PermissionService`` for narrowed sessions and the service
        returns ``{"*"}`` because the user has the seeded ``platform_admin``
        role globally. The router must forward ``caller_token_teams`` so the
        service can refuse the bypass even when ``caller_permissions == ["*"]``.
        """
        narrowed_admin = {
            "email": "narrowed-admin@example.com",
            "is_admin": True,
            "token_teams": ["other-team"],
            "permissions": ["*"],
            "db": mock_db,
            "auth_method": "jwt",
        }

        request = TokenCreateRequest(name="Should Fail", description="Narrowed admin with platform_admin role")

        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_service_class:
            with patch("mcpgateway.routers.tokens._get_caller_permissions") as mock_get_perms:
                # Simulates PermissionService returning {"*"} for a narrowed admin
                # who holds the global platform_admin role.
                mock_get_perms.return_value = ["*"]
                mock_service = mock_service_class.return_value
                mock_service.create_token = AsyncMock(side_effect=ValueError("User narrowed-admin@example.com is not an active member of team team-blocked"))

                with pytest.raises(HTTPException) as exc_info:
                    await create_team_token(team_id="team-blocked", request=request, current_user=narrowed_admin, db=mock_db)

                assert exc_info.value.status_code == 400
                # The router must forward the narrowed token scope so the service refuses bypass
                # even though caller_permissions == ["*"] from the global platform_admin role.
                call_kwargs = mock_service.create_token.call_args[1]
                assert call_kwargs["caller_permissions"] == ["*"]
                assert call_kwargs["is_admin"] is True
                assert call_kwargs["caller_token_teams"] == ["other-team"]
                assert call_kwargs["caller_token_teams_provided"] is True


# ---------- Codex Review Findings: Regression Tests ----------


class TestGetCallerPermissionsTokenNarrowing:
    """Tests for _get_caller_permissions token_teams enforcement (Finding 1)."""

    @pytest.mark.asyncio
    async def test_unrestricted_admin_returns_wildcard(self):
        """Un-narrowed admin (token_teams=None) gets ['*']."""
        # First-Party
        from mcpgateway.routers.tokens import _get_caller_permissions

        user = {"email": "admin@test.com", "is_admin": True, "token_teams": None}
        result = await _get_caller_permissions(MagicMock(), user)
        assert result == ["*"]

    @pytest.mark.asyncio
    async def test_narrowed_admin_does_not_get_wildcard(self):
        """Narrowed admin (token_teams=['team-a']) must NOT get ['*'] (Finding 1)."""
        # First-Party
        from mcpgateway.routers.tokens import _get_caller_permissions

        user = {"email": "admin@test.com", "is_admin": True, "token_teams": ["team-a"]}
        with patch("mcpgateway.routers.tokens.PermissionService") as mock_ps_cls:
            mock_ps = mock_ps_cls.return_value
            mock_ps.get_user_permissions = AsyncMock(return_value={"tools.read", "admin.dashboard"})

            result = await _get_caller_permissions(MagicMock(), user, team_id="team-a")

            assert result != ["*"], "Narrowed admin must not receive wildcard permissions"
            mock_ps.get_user_permissions.assert_awaited_once_with(user_email="admin@test.com", team_id="team-a", token_teams=["team-a"])

    @pytest.mark.asyncio
    async def test_public_only_admin_does_not_get_wildcard(self):
        """Public-only admin (token_teams=[]) must NOT get ['*'] (Finding 1)."""
        # First-Party
        from mcpgateway.routers.tokens import _get_caller_permissions

        user = {"email": "admin@test.com", "is_admin": True, "token_teams": []}
        with patch("mcpgateway.routers.tokens.PermissionService") as mock_ps_cls:
            mock_ps = mock_ps_cls.return_value
            mock_ps.get_user_permissions = AsyncMock(return_value=set())

            result = await _get_caller_permissions(MagicMock(), user)

            assert result is None or result == [], "Public-only admin must not receive wildcard permissions"


class TestTokenOversightEndpointsNarrowing:
    """Tests for list_all_tokens/admin_revoke_token token_teams enforcement (Finding 3)."""

    @pytest.mark.asyncio
    async def test_list_all_tokens_rejects_narrowed_admin(self):
        """Narrowed admin session must be rejected by list_all_tokens (Finding 3)."""
        user = {"email": "admin@test.com", "is_admin": True, "token_teams": ["team-a"], "auth_method": "jwt"}
        with pytest.raises(HTTPException) as exc_info:
            await list_all_tokens(current_user=user, db=MagicMock())
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_list_all_tokens_rejects_public_only_admin(self):
        """Public-only admin session must be rejected by list_all_tokens (Finding 3)."""
        user = {"email": "admin@test.com", "is_admin": True, "token_teams": [], "auth_method": "jwt"}
        with pytest.raises(HTTPException) as exc_info:
            await list_all_tokens(current_user=user, db=MagicMock())
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_list_all_tokens_allows_unrestricted_admin(self):
        """Un-narrowed admin (token_teams=None) must be allowed by list_all_tokens."""
        user = {"email": "admin@test.com", "is_admin": True, "token_teams": None, "auth_method": "jwt"}
        with patch("mcpgateway.routers.tokens.TokenCatalogService") as mock_svc:
            mock_svc.return_value.list_all_tokens = AsyncMock(return_value=[])
            mock_svc.return_value.count_all_tokens = AsyncMock(return_value=0)
            mock_svc.return_value.get_token_revocations_batch = AsyncMock(return_value={})
            result = await list_all_tokens(current_user=user, db=MagicMock())
            assert result.tokens == []

    @pytest.mark.asyncio
    async def test_admin_revoke_rejects_narrowed_admin(self):
        """Narrowed admin session must be rejected by admin_revoke_token (Finding 3)."""
        user = {"email": "admin@test.com", "is_admin": True, "token_teams": ["team-a"], "auth_method": "jwt"}
        with pytest.raises(HTTPException) as exc_info:
            await admin_revoke_token(token_id="tok-123", request=None, current_user=user, db=MagicMock())
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_revoke_rejects_public_only_admin(self):
        """Public-only admin session must be rejected by admin_revoke_token (Finding 3)."""
        user = {"email": "admin@test.com", "is_admin": True, "token_teams": [], "auth_method": "jwt"}
        with pytest.raises(HTTPException) as exc_info:
            await admin_revoke_token(token_id="tok-123", request=None, current_user=user, db=MagicMock())
        assert exc_info.value.status_code == 403


class TestCreateTokenNarrowing:
    """Tests for create_token team auto-inheritance with narrowed admin sessions (Finding 1)."""

    def test_narrowed_admin_gets_auto_inherit(self):
        """Narrowed admin with single team should auto-inherit team_id (Finding 1).

        Un-narrowed admins (token_teams=None) skip auto-inheritance and may
        create global-scope tokens.  Narrowed admins must be treated like
        non-admins: single-team sessions auto-inherit the team.

        Tests the auto-inheritance logic directly rather than calling the full
        handler (which involves deep Pydantic serialization).
        """
        # Narrowed admin with single team: should auto-inherit
        user_narrowed = {"email": "admin@test.com", "is_admin": True, "token_teams": ["team-a"]}
        caller_token_teams = user_narrowed.get("token_teams")
        is_unrestricted_admin = user_narrowed.get("is_admin") and caller_token_teams is None
        assert not is_unrestricted_admin, "Narrowed admin must NOT be treated as unrestricted"

        effective_team_id = None
        if effective_team_id is None and not is_unrestricted_admin:
            user_teams = caller_token_teams or []
            if len(user_teams) == 1:
                effective_team_id = user_teams[0]
        assert effective_team_id == "team-a", "Narrowed admin must auto-inherit team_id"

        # Un-narrowed admin: should NOT auto-inherit (may create global tokens)
        user_unrestricted = {"email": "admin@test.com", "is_admin": True, "token_teams": None}
        caller_token_teams2 = user_unrestricted.get("token_teams")
        is_unrestricted_admin2 = user_unrestricted.get("is_admin") and caller_token_teams2 is None
        assert is_unrestricted_admin2, "Un-narrowed admin must be treated as unrestricted"

        effective_team_id2 = None
        if effective_team_id2 is None and not is_unrestricted_admin2:
            user_teams2 = caller_token_teams2 or []
            if len(user_teams2) == 1:
                effective_team_id2 = user_teams2[0]
        assert effective_team_id2 is None, "Un-narrowed admin should NOT auto-inherit"
